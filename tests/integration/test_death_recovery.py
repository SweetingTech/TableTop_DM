from __future__ import annotations

import uuid

import pytest

from domains.tabletop.recovery import VITALS
from domains.tabletop.world_time import read_clock
from tests.integration.test_action_rules import durable_mark
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_death_recovery_api import defeat
from tests.unit.kernel.test_timed_effects_api import physical_projection, projected_advance

pytestmark = pytest.mark.integration


def test_saved_seed_boundaries_restart_late_retry_and_recorded_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, state, receipt = defeat(app, game)
    admin, player, card, path, run, target, base = game
    expected = state.working_copy()
    projected_advance(expected, 4000)
    seed = state.projections[VITALS][target]["seed"]
    advance_clock(admin, base, 5)
    restored, client = fresh_client(tmp_path)
    source = restored.extensions["world_runner"].snapshot()
    branch = uuid.UUID(base["branch_id"])
    assert source.states.get(branch).projections[VITALS][target]["seed"] == seed
    mark = durable_mark(integration_stack, base)
    repeated = client.post(
        "/api/v2/commands",
        json={
            **base,
            "actor_id": receipt["event"]["actor_id"],
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.magic.invoke",
            "parameters": {"spell_id": "ARCANE_BOLT", "target_id": target},
            "idempotency_key": "defeat",
            "seed": 999,
        },
    )
    assert repeated.status_code == 200, repeated.get_json()
    for field in ("result", "event", "state_hash"):
        assert repeated.get_json()[field] == receipt[field]
    assert durable_mark(integration_stack, base) == mark
    advance_clock(client, base, 4000)
    actual = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert physical_projection(actual) == physical_projection(expected)
    replay = client.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_intermediate_save_failure_rolls_back_body_vitals_clock_and_ledger(
    integration_stack, monkeypatch, tmp_path
):
    import domains.tabletop.activities as activities

    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, state, receipt = defeat(app, game)
    admin, player, card, path, run, target, base = game
    branch = uuid.UUID(base["branch_id"])
    mark = durable_mark(integration_stack, base)
    original_hash = state.state_hash
    original = activities.expire

    def fail(state, now):
        original(state, now)
        if now >= 6:
            raise ValueError("injected death-save boundary failure")

    clock = read_clock(state)
    with monkeypatch.context() as patch:
        patch.setattr(activities, "expire", fail)
        failed = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "tabletop.clock.advance",
                "idempotency_key": "failed-death-save",
                "parameters": {
                    "expected_epoch": clock.epoch,
                    "expected_seconds": clock.seconds,
                    "to_seconds": 12,
                },
            },
        )
        assert failed.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restored, client = fresh_client(tmp_path)
    fresh = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert fresh.state_hash == original_hash
    assert fresh.projections[VITALS][target]["rolls"] == []
    advance_clock(client, base, 12)
    assert (
        restored.extensions["world_runner"].snapshot().states.get(branch).state_hash
        != original_hash
    )
