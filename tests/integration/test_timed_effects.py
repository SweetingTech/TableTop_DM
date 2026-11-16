from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from cognition.projector import WorldEventProjector
from domains.tabletop import register_tabletop
from kernel.command_bus import CommandBus
from kernel.contracts import CommandProposal
from kernel.state import InMemoryStateStore
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock, clock_path
from tests.unit.kernel.test_timed_effects_api import condition
from tests.unit.kernel.test_world_time import NOW, api_command

pytestmark = pytest.mark.integration


def test_effect_parity_midstep_expiry_restart_late_retry_and_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    source = app.extensions["world_runner"].snapshot()
    branch = uuid.UUID(base["branch_id"])
    actor_id = source.entities[(branch, uuid.UUID(target))].controller_actor_id
    request = CommandProposal(
        **base,
        actor_id=actor_id,
        command_type="tabletop.condition.apply",
        parameters={"target_id": target, "condition": "stunned", "duration_seconds": 5},
        idempotency_key="stun",
    )
    store = InMemoryStateStore()
    store.add(source.states.get(branch).working_copy())
    reference = register_tabletop(CommandBus(store))
    reference.execute(request, source.authority(request.world_id, actor_id))
    receipt = admin.post("/api/v2/commands", json=request.model_dump(mode="json"))
    assert receipt.status_code == 200, receipt.get_json()
    assert (
        app.extensions["world_runner"].snapshot().states.get(branch).state_hash
        == store.get(branch).state_hash
    )
    blessing = api_command(
        admin,
        base,
        "tabletop.divine.bless",
        {"target_id": target, "blessing": "Hope", "duration_turns": 2},
        "hope",
    )
    mark = durable_mark(integration_stack, base)
    denied = player.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.condition.apply",
            "idempotency_key": "denied",
            "parameters": {
                "target_id": card["entity_id"],
                "condition": "stunned",
                "duration_seconds": 5,
            },
        },
    )
    assert denied.status_code == 403 and durable_mark(integration_stack, base) == mark
    restored, client = fresh_client(tmp_path)
    assert (
        client.post("/api/v2/commands", json=request.model_dump(mode="json")).get_json()
        == receipt.get_json()
    )
    assert durable_mark(integration_stack, base) == mark
    advance_clock(client, base, 10)
    state = restored.extensions["world_runner"].snapshot().states.get(branch)
    body = state.projections["tabletop.entities"][target]
    assert body["weeded_units"] == 5 and body["timed_conditions"] == {}
    assert body["blessings"] == [{"name": "Hope", "remaining_turns": 1, "expires_seconds": 12}]
    mark = durable_mark(integration_stack, base)
    assert (
        client.post("/api/v2/commands", json=request.model_dump(mode="json")).get_json()
        == receipt.get_json()
    )
    assert (
        api_command(
            client,
            base,
            "tabletop.divine.bless",
            {"target_id": target, "blessing": "Hope", "duration_turns": 2},
            "hope",
        )
        == blessing
    )
    assert durable_mark(integration_stack, base) == mark
    advance_clock(client, base, 12)
    assert (
        restored.extensions["world_runner"]
        .snapshot()
        .states.get(branch)
        .projections["tabletop.entities"][target]["blessings"]
        == []
    )
    replay = client.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_expiry_batch_rolls_back_after_intermediate_boundary_failure(
    integration_stack, monkeypatch, tmp_path
):
    import domains.tabletop.activities as activities

    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    condition(admin, base, target)
    mark = durable_mark(integration_stack, base)
    original = activities.expire

    def fail_after_expiry(state, now):
        original(state, now)
        if now >= 5:
            raise ValueError("injected boundary failure")

    monkeypatch.setattr(activities, "expire", fail_after_expiry)
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.clock.advance",
            "idempotency_key": "advance-retry",
            "parameters": {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 10},
        },
    )
    assert response.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restarted, operator = fresh_client(tmp_path)
    body = (
        restarted.extensions["world_runner"]
        .snapshot()
        .states.get(uuid.UUID(base["branch_id"]))
        .projections["tabletop.entities"][target]
    )
    assert len(body["timed_conditions"]) == 1 and body.get("weeded_units", 0) == 0
    monkeypatch.setattr(activities, "expire", original)
    advance_clock(operator, base, 10)
    body = (
        restarted.extensions["world_runner"]
        .snapshot()
        .states.get(uuid.UUID(base["branch_id"]))
        .projections["tabletop.entities"][target]
    )
    assert body["timed_conditions"] == {} and body["weeded_units"] == 5


def test_restarted_stand_in_recovers_after_real_condition_expiry(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    condition(admin, base, card["entity_id"])
    clock = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": False,
            "seconds_per_tick": 5,
        },
        "resume",
    )
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 1,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    restarted, client = player_after_restart(tmp_path, player)
    runner = restarted.extensions["character_runner"]
    before = client.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    mark = durable_mark(integration_stack, base)
    for _ in range(4):
        assert runner.run_once() == 0
    assert (
        client.get(path + "/control", query_string={"run_id": run}).get_json()["control"] == before
    )
    assert durable_mark(integration_stack, base) == mark
    assert restarted.extensions["world_runner"].run_once(NOW + timedelta(seconds=1)) == 1
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    assert runner.run_once() == 1
    control = client.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["step"] == 1 and control["failures"] == 0
    # Leave no running test clock for later real world-runner process tests.
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 2,
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": True,
        },
        "stop-test-clock",
    )
