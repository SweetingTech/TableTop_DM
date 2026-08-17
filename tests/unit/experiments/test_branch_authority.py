from __future__ import annotations

import uuid

import pytest

from experiments.executor import ApplicationBranchExecutor
from experiments.models import SnapshotReference
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
