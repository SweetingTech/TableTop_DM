from __future__ import annotations

import uuid

import pytest

from domains.tabletop.activities import ACTIVITIES
from domains.tabletop.world_time import read_clock
from tests.integration.test_action_rules import durable_mark
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_rest_recovery_api import prepare_rest, rest
from tests.unit.kernel.test_timed_effects_api import physical_projection, projected_advance

pytestmark = pytest.mark.integration


def test_rest_progress_caps_restart_late_retry_and_recorded_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, state = prepare_rest(app, game)
    admin, player, card, path, run, target, base = game
    receipt = rest(player, base, card)
    state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    expected = state.working_copy()
    projected_advance(expected, 28900)
    advance_clock(admin, base, 3599)
    restored, client = fresh_client(tmp_path)
    branch = uuid.UUID(base["branch_id"])
    current = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert (
        current.projections[ACTIVITIES][card["entity_id"]]["details"]["recovery"]["elapsed_seconds"]
        == 3599
    )
    mark = durable_mark(integration_stack, base)
    retry = client.post(
        "/api/v2/commands",
        json={
            **base,
            "actor_id": receipt["event"]["actor_id"],
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.rest.start",
            "parameters": {"kind": "LONG"},
            "idempotency_key": "rest",
        },
    )
    assert retry.status_code == 200, retry.get_json()
    for field in ("result", "event", "state_hash"):
        assert retry.get_json()[field] == receipt[field]
    assert durable_mark(integration_stack, base) == mark
    advance_clock(client, base, 3600)
    advance_clock(client, base, 28900)
    current = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert physical_projection(current) == physical_projection(expected)
    replay = client.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_recovery_failure_rolls_back_every_resource_activity_clock_and_ledger(
    integration_stack, monkeypatch, tmp_path
):
    import domains.tabletop.rest as recovery

    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, state = prepare_rest(app, game)
    admin, player, card, path, run, target, base = game
    rest(player, base, card)
    state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    original_hash = state.state_hash
    mark = durable_mark(integration_stack, base)
    original = recovery.recover

    def fail(activity, body, start, until, **kwargs):
        value = original(activity, body, start, until, **kwargs)
        if until >= 3600:
            raise ValueError("injected rest recovery failure")
        return value

    clock = read_clock(state)
    with monkeypatch.context() as patch:
        patch.setattr(recovery, "recover", fail)
        response = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "tabletop.clock.advance",
                "idempotency_key": "failed-rest",
                "parameters": {
                    "expected_epoch": clock.epoch,
                    "expected_seconds": 0,
                    "to_seconds": 28800,
                },
            },
        )
        assert response.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restored, client = fresh_client(tmp_path)
    current = (
        restored.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    )
    assert current.state_hash == original_hash
    advance_clock(client, base, 28800)
    body = (
        restored.extensions["world_runner"]
        .snapshot()
        .states.get(uuid.UUID(base["branch_id"]))
        .projections["tabletop.entities"][card["entity_id"]]
    )
    assert body["hp"] == 12 and body["mana"] == 8
