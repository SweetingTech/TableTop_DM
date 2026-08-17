from __future__ import annotations

import uuid

import pytest

from kernel.application import SimulationApplication
from kernel.contracts import ActorKind, CommandProposal
from kernel.errors import AuthorizationDenied

pytestmark = pytest.mark.unit


def test_authority_and_control_are_world_scoped_and_runs_cannot_cross(tmp_path) -> None:
    simulation = SimulationApplication(tmp_path / "snapshots")
    first = simulation.create_world("First authority world")
    second = simulation.create_world("Second authority world")
    actor = simulation.create_actor(
        "Scoped operator",
        ActorKind.HUMAN,
        {"PLAYER"},
        {"action.propose", "action.commit", "entity.control"},
        world_id=first.world_id,
    )
    simulation.grant_authority(
        second.world_id,
        actor.actor_id,
        roles={"OBSERVER"},
        capabilities={"world.read"},
    )
    entity = simulation.create_entity(
        first.world_id,
        first.canonical_branch_id,
        "Scoped hero",
        "PLAYER_CHARACTER",
        {"x": 0, "y": 0},
        controller_actor_id=actor.actor_id,
    )
    assert (
        entity.entity_id
        in simulation.authority(first.world_id, actor.actor_id).controlled_entity_ids
    )
    assert (
        entity.entity_id
        not in simulation.authority(second.world_id, actor.actor_id).controlled_entity_ids
    )

    first_run = next(run for run in simulation.runs.values() if run.world_id == first.world_id)
    second_run = next(run for run in simulation.runs.values() if run.world_id == second.world_id)
    accepted = simulation.submit(
        CommandProposal(
            command_type="tabletop.console.submit",
            world_id=first.world_id,
            branch_id=first.canonical_branch_id,
            run_id=first_run.run_id,
            actor_id=actor.actor_id,
            parameters={"text": "Scoped to the first world."},
            idempotency_key="first-world-command",
        )
    )
    assert accepted.result.accepted is True

    with pytest.raises(AuthorizationDenied, match="Missing capabilities"):
        simulation.submit(
            CommandProposal(
                command_type="tabletop.console.submit",
                world_id=second.world_id,
                branch_id=second.canonical_branch_id,
                run_id=second_run.run_id,
                actor_id=actor.actor_id,
                parameters={"text": "Must not inherit first-world power."},
                idempotency_key="second-world-command",
            )
        )

    with pytest.raises(ValueError, match="run does not belong"):
        simulation.submit(
            CommandProposal(
                command_id=uuid.uuid4(),
                command_type="tabletop.console.submit",
                world_id=first.world_id,
                branch_id=first.canonical_branch_id,
                run_id=second_run.run_id,
                actor_id=actor.actor_id,
                parameters={"text": "Cross-world run substitution."},
                idempotency_key="cross-world-run",
            )
        )

    before = simulation.states.get(first.canonical_branch_id).working_copy()
    rejected_entity_id = uuid.uuid4()
    with pytest.raises(AuthorizationDenied, match="no authority"):
        simulation.submit(
            CommandProposal(
                command_type="tabletop.entity.spawn",
                world_id=first.world_id,
                branch_id=first.canonical_branch_id,
                run_id=first_run.run_id,
                actor_id=actor.actor_id,
                parameters={
                    "entity_id": rejected_entity_id,
                    "name": "Must not exist",
                    "entity_type": "NPC",
                    "public_state": {"x": 2, "y": 2},
                    "secret_state": {"hidden": True},
                    "controller_actor_id": uuid.uuid4(),
                },
                idempotency_key="invalid-controller-spawn",
            )
        )
    after = simulation.states.get(first.canonical_branch_id)
    assert (after.version, after.state_hash) == (before.version, before.state_hash)
    assert (first.canonical_branch_id, rejected_entity_id) not in simulation.entities
