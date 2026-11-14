from __future__ import annotations

import uuid

import pytest

from kernel.application import SimulationApplication
from kernel.contracts import CommandProposal

pytestmark = pytest.mark.unit


def test_spawn_retry_returns_original_receipt_and_snapshot_excludes_later_body(tmp_path):
    app = SimulationApplication(tmp_path)
    ids = app.bootstrap_demo()
    snapshot = app.create_snapshot(ids["world_id"])
    entity = uuid.uuid4()
    proposal = CommandProposal(
        command_type="tabletop.entity.spawn",
        world_id=ids["world_id"],
        branch_id=ids["branch_id"],
        run_id=ids["run_id"],
        actor_id=ids["actor_id"],
        idempotency_key="retry-spawn",
        parameters={
            "entity_id": str(entity),
            "name": "Later entity",
            "entity_type": "NPC",
            "public_state": {"x": 7, "y": 8},
        },
    )
    first = app.submit(proposal)
    assert app.submit(proposal) == first
    assert (
        len([event for event in app.events.values() if event.event_id == first.event.event_id]) == 1
    )
    with pytest.raises(ValueError, match="already exists"):
        app.submit(
            proposal.model_copy(
                update={"command_id": uuid.uuid4(), "idempotency_key": "different-spawn"}
            )
        )
    branch, _ = app.create_trial(ids["world_id"], snapshot.snapshot_id, seed=14)
    assert (branch.branch_id, entity) not in app.entities
    assert str(entity) not in branch.projections["tabletop.entities"]
