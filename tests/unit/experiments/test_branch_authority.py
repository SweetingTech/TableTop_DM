from __future__ import annotations

import uuid

import pytest

from experiments.executor import ApplicationBranchExecutor
from experiments.models import ScenarioDefinition, SnapshotReference
from kernel.application import SimulationApplication
from kernel.contracts import ActorKind

pytestmark = pytest.mark.unit


def test_scenario_executor_requires_world_scoped_branch_authority(tmp_path) -> None:
    simulation = SimulationApplication(tmp_path / "snapshots")
    ids = simulation.bootstrap_demo()
    manifest = simulation.create_snapshot(ids["world_id"])
    reference = SnapshotReference(
        snapshot_id=manifest.snapshot_id,
        world_id=manifest.world_id,
        canonical_branch_id=manifest.branch_id,
        state_hash=manifest.state_hash,
        contract_version=manifest.contract_version,
    )
    observer = simulation.create_actor(
        "Scenario observer",
        ActorKind.HUMAN,
        {"OBSERVER"},
        {"world.read"},
        world_id=ids["world_id"],
    )
    before = len(simulation.states.all())

    with pytest.raises(PermissionError, match="trial branches"):
        ApplicationBranchExecutor(simulation, observer.actor_id).create_trial_branch(
            reference,
            uuid.uuid4(),
            17,
        )

    assert len(simulation.states.all()) == before


def populated_snapshot(tmp_path):
    simulation = SimulationApplication(tmp_path / "snapshots")
    ids = simulation.bootstrap_demo()
    manifest = simulation.create_snapshot(ids["world_id"])
    reference = SnapshotReference(
        snapshot_id=manifest.snapshot_id,
        world_id=manifest.world_id,
        canonical_branch_id=manifest.branch_id,
        state_hash=manifest.state_hash,
        contract_version=manifest.contract_version,
    )
    return simulation, ids, reference


def test_scenario_restores_frozen_entities_before_first_command(tmp_path):
    simulation, ids, reference = populated_snapshot(tmp_path)
    frozen = simulation.snapshot_store.load(simulation.snapshots[reference.snapshot_id])
    for (branch_id, _), entity in simulation.entities.items():
        if branch_id == ids["branch_id"]:
            entity.secret_state["future"] = "must not reach trial"
    persisted = []
    simulation.snapshot_persister = lambda manifest, version: persisted.append(manifest)
    executor = ApplicationBranchExecutor(simulation, ids["actor_id"])
    trial_id = uuid.uuid4()
    trial = executor.create_trial_branch(reference, trial_id, 17)
    assert executor.create_trial_branch(reference, trial_id, 17) == trial
    assert simulation.branch_snapshot_ids[trial.branch_id] == reference.snapshot_id
    branch = simulation.states.get(trial.branch_id)
    for key, metadata in frozen["entities"].items():
        entity = simulation.entities[(trial.branch_id, uuid.UUID(key))]
        assert entity.secret_state == metadata["secret_state"]
        assert str(entity.controller_actor_id) == str(metadata["controller_actor_id"])
        assert entity.name == frozen["projections"]["tabletop.entities"][key]["name"]
    output = executor.execute(
        ScenarioDefinition(scenario_id="populated-world", version="1.0.0"),
        trial,
        None,
        17,
        {},
        lambda: False,
    )
    assert output.status == "COMPLETED" and len(persisted) == 1
    assert simulation.snapshot_store.load(persisted[0])["entities"]
    assert simulation.replay(trial.branch_id).state_hash == branch.state_hash
    other = executor.create_trial_branch(reference, uuid.uuid4(), 17)
    assert other.branch_id != trial.branch_id and other.run_id != trial.run_id
    assert simulation.states.get(other.branch_id).state_hash == reference.state_hash


@pytest.mark.parametrize("field", ["world_id", "canonical_branch_id", "contract_version"])
def test_scenario_rejects_mismatched_snapshot_reference_before_branch_creation(tmp_path, field):
    simulation, ids, reference = populated_snapshot(tmp_path)
    if field == "world_id":
        other = simulation.create_world("Other world")
        simulation.grant_authority(
            other.world_id, ids["actor_id"], roles=set(), capabilities={"run.branch"}
        )
        value = other.world_id
    else:
        value = uuid.uuid4() if field == "canonical_branch_id" else "2.0.0"
    before = len(simulation.states.all())
    with pytest.raises(ValueError, match="immutable manifest"):
        ApplicationBranchExecutor(simulation, ids["actor_id"]).create_trial_branch(
            reference.model_copy(update={field: value}), uuid.uuid4(), 17
        )
    assert len(simulation.states.all()) == before
