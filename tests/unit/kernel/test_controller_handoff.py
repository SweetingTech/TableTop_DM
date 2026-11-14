from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from kernel.errors import AuthorizationDenied
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def test_explicit_handoff_runner_budget_and_human_takeover(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    sim = app.extensions["simulation"]
    ids = app.extensions["demo_ids"]
    events = len(sim.events)
    context = player.get(path + "/context", query_string={"run_id": run}).get_json()
    request = {
        "run_id": run,
        "expected_epoch": 0,
        "mode": "AUTONOMOUS",
        "idempotency_key": "leave",
        "max_steps": 1,
        "interval_ms": 100,
    }
    handed = player.post(path + "/control", json=request)
    assert handed.status_code == 200, handed.get_json()
    assert player.post(path + "/control", json=request).get_json() == handed.get_json()
    state = handed.get_json()["state"]
    assert state["mode"] == "AUTONOMOUS" and state["epoch"] == 1
    assert state["owner_actor_id"] != state["executor_actor_id"]
    assert len(sim.events) == events
    assert (
        player.get(path + "/context", query_string={"run_id": run}).get_json()["evidence_hash"]
        == context["evidence_hash"]
    )
    body = {
        "command_type": "tabletop.spatial.move",
        "world_id": card["world_id"],
        "branch_id": str(ids["branch_id"]),
        "run_id": run,
        "embodied_entity_id": card["entity_id"],
        "parameters": {"dx": 1, "dy": 0},
        "idempotency_key": "human-while-away",
    }
    assert player.post("/api/v2/commands", json=body).status_code == 403
    assert app.extensions["character_runner"].run_once() == 1
    assert app.extensions["character_runner"].run_once() == 0
    assert len(sim.events) == events + 1
    current = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert current["step"] == 1 and current["mode"] == "PAUSED"
    assert current["last_error"] == "step_limit"
    taken = player.post(
        path + "/control",
        json={**request, "mode": "HUMAN", "expected_epoch": 1, "idempotency_key": "return"},
    )
    assert taken.status_code == 200
    assert taken.get_json()["state"]["epoch"] == 2
    assert player.post("/api/v2/commands", json={**body, "control_epoch": 1}).status_code == 403
    # A delayed legacy request cannot be silently stamped with a fresh epoch.
    assert player.post("/api/v2/commands", json=body).status_code == 403
    assert player.post("/api/v2/commands", json={**body, "control_epoch": 2}).status_code == 200
    assert not any(
        "control" in event.event_type or "handoff" in event.event_type
        for event in sim.events.values()
    )


def test_pending_agent_proposal_cannot_commit_after_takeover(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, _, _, path, run, _ = setup_bound_character(app)
    body = {"run_id": run, "expected_epoch": 0, "mode": "AUTONOMOUS", "idempotency_key": "leave"}
    state = player.post(path + "/control", json=body).get_json()["state"]
    controllers = app.extensions["controllers"]
    controller = controllers.due()[0]
    advice = app.extensions["character_decisions"].decide(
        controller.scope,
        controller.executor_actor_id,
        f"controller:{controller.epoch}:step:{controller.step}",
        controller,
    )
    captured_actor = app.extensions["simulation"].authority(
        controller.world_id, controller.executor_actor_id
    )
    assert (
        player.post(
            path + "/control",
            json={**body, "mode": "HUMAN", "expected_epoch": 1, "idempotency_key": "take"},
        ).status_code
        == 200
    )
    sim = app.extensions["simulation"]
    count = len(sim.events)
    with pytest.raises(AuthorizationDenied, match="controller changed"):
        sim.bus.execute(advice.outcome.proposal, captured_actor)
    assert len(sim.events) == count
    assert (
        player.post(path + "/control", json={**body, "idempotency_key": "stale"}).status_code == 409
    )
    assert state["executor_actor_id"] != str(uuid.UUID(state["owner_actor_id"]))


def test_invalidated_action_pauses_instead_of_spinning(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, _, _, path, run, _ = setup_bound_character(app)
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "expected_epoch": 0,
                "mode": "AUTONOMOUS",
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    controller = app.extensions["controllers"].due()[0]
    advice = app.extensions["character_decisions"].decide(
        controller.scope,
        controller.executor_actor_id,
        f"controller:{controller.epoch}:step:0",
        controller,
    )
    destination = advice.outcome.proposal.parameters
    app.extensions["simulation"].states.get(controller.branch_id).projections[
        "tabletop.obstacles"
    ] = {"hidden-wall": {"x": destination["dx"], "y": destination["dy"]}}
    count = len(app.extensions["simulation"].events)
    assert app.extensions["character_runner"].run_once() == 0
    state = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert (
        state["mode"] == "PAUSED" and state["last_error"] == "action_failed" and state["step"] == 0
    )
    assert app.extensions["character_runner"].run_once() == 0
    assert len(app.extensions["simulation"].events) == count


def test_paused_run_and_projection_circuit_are_bounded(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    sim = app.extensions["simulation"]
    captured = []
    sim.configure_subjective_projector(captured.append)
    ids = app.extensions["demo_ids"]
    assert (
        player.post(
            "/api/v2/commands",
            json={
                "command_type": "tabletop.dialogue.speak",
                "world_id": card["world_id"],
                "branch_id": str(ids["branch_id"]),
                "run_id": run,
                "embodied_entity_id": card["entity_id"],
                "parameters": {"text": "Remember this."},
                "idempotency_key": "pending-memory",
            },
        ).status_code
        == 200
    )
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "expected_epoch": 0,
                "mode": "AUTONOMOUS",
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    runner = app.extensions["character_runner"]
    live = sim.runs[uuid.UUID(run)]
    sim.runs[live.run_id] = live.model_copy(update={"status": "PAUSED"})
    assert runner.run_once() == 0
    sim.runs[live.run_id] = live
    for _ in range(40):
        state = next(iter(app.extensions["controllers"].rows.values()))
        sim.controller_states[state.key] = state.model_copy(
            update={"next_due": datetime.now(UTC) - timedelta(seconds=1)}
        )
        assert runner.run_once() == 0
    state = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert state["mode"] == "PAUSED" and state["failures"] == 40 and state["step"] == 0
    assert len(captured) == 1
