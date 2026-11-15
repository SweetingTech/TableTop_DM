from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from domains.tabletop.world_time import read_clock
from kernel.application import SimulationApplication
from kernel.contracts import ActorKind, CommandProposal
from kernel.errors import AuthorizationDenied
from kernel.world_runner import WorldRunner
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene

pytestmark = pytest.mark.unit
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def reference():
    app = SimulationApplication()
    ids = app.bootstrap_demo()
    return app, ids


def send(app, ids, command, parameters, key, **kwargs):
    return app.submit(
        CommandProposal(
            **ids, command_type=command, parameters=parameters, idempotency_key=key, **kwargs
        )
    )


def configure(app, ids, **changes):
    clock = read_clock(app.states.get(ids["branch_id"]))
    executor = uuid.uuid5(ids["world_id"], "clock-executor")
    if executor not in app.actors:
        app.create_actor(
            "World clock",
            ActorKind.AGENT,
            set(),
            {"world.read", "action.propose", "action.commit"},
            actor_id=executor,
            world_id=ids["world_id"],
        )
    return send(
        app,
        ids,
        "tabletop.clock.configure",
        {
            "expected_epoch": clock.epoch if clock else 0,
            "executor_actor_id": str(executor),
            "wall_time": NOW.isoformat(),
            **changes,
        },
        "configure:" + str(clock.epoch if clock else 0),
    )


def advance(app, ids, until):
    clock = read_clock(app.states.get(ids["branch_id"]))
    return send(
        app,
        ids,
        "tabletop.clock.advance",
        {
            "expected_epoch": clock.epoch,
            "expected_seconds": clock.seconds,
            "to_seconds": until,
        },
        "advance:" + str(until),
    )


def test_freeze_pause_epoch_fence_and_exact_receipt_after_pause():
    app, ids = reference()
    configure(app, ids, paused=False, seconds_per_tick=10)
    runner = WorldRunner(lambda: app)
    assert runner.run_once(NOW) == 0
    assert runner.run_once(NOW + timedelta(seconds=20)) == 1
    assert read_clock(app.states.get(ids["branch_id"])).seconds == 10
    assert runner.run_once(NOW + timedelta(seconds=20)) == 0
    original = app.command_history[ids["branch_id"]][-1]
    configure(app, ids, paused=True)
    assert runner.run_once(NOW + timedelta(days=1)) == 0
    assert app.submit(original.proposal).state_hash == original.expected_state_hash
    before = app.states.get(ids["branch_id"]).state_hash
    with pytest.raises(ValueError):
        app.submit(original.proposal.model_copy(update={"idempotency_key": "stale-new"}))
    assert app.states.get(ids["branch_id"]).state_hash == before


def test_catch_up_is_bounded_and_stops_exactly_at_until_boundary():
    hashes = []
    for offset in (UTC, timezone(timedelta(hours=-5))):
        app, ids = reference()
        configure(
            app,
            ids,
            paused=False,
            seconds_per_tick=10,
            offline_policy="CATCH_UP",
            max_catch_up_ticks=3,
            until_seconds=50,
            wall_time=NOW.astimezone(offset).isoformat(),
        )
        runner = WorldRunner(lambda app=app: app)
        assert runner.run_once(NOW + timedelta(seconds=100)) == 1
        assert read_clock(app.states.get(ids["branch_id"])).seconds == 30
        assert runner.run_once(NOW + timedelta(seconds=100)) == 1
        clock = read_clock(app.states.get(ids["branch_id"]))
        assert clock.seconds == 50 and clock.paused
        assert runner.run_once(NOW + timedelta(seconds=200)) == 0
        hashes.append(app.states.get(ids["branch_id"]).state_hash)
        assert app.replay(ids["branch_id"]).state_hash == hashes[-1]
    assert hashes[0] == hashes[1]


def test_paused_run_and_wrong_executor_reject_without_writes():
    app, ids = reference()
    configure(app, ids, paused=False)
    tick = CommandProposal(
        **{**ids, "actor_id": uuid.uuid5(ids["world_id"], "clock-executor")},
        command_type="tabletop.clock.tick",
        idempotency_key="tick",
        parameters={"epoch": 1, "step": 0, "wall_time": (NOW + timedelta(seconds=2)).isoformat()},
    )
    before = app.states.get(ids["branch_id"]).state_hash
    app.runs[ids["run_id"]] = app.runs[ids["run_id"]].model_copy(update={"status": "PAUSED"})
    with pytest.raises(AuthorizationDenied):
        app.submit(tick)
    assert app.states.get(ids["branch_id"]).state_hash == before
    app.runs[ids["run_id"]] = app.runs[ids["run_id"]].model_copy(update={"status": "ACTIVE"})
    other = app.create_actor(
        "Other",
        ActorKind.AGENT,
        set(),
        {"world.read", "action.propose", "action.commit"},
        world_id=ids["world_id"],
    )
    with pytest.raises(ValueError):
        app.submit(tick.model_copy(update={"actor_id": other.actor_id}))
    assert app.states.get(ids["branch_id"]).state_hash == before


def test_trial_clock_is_independent_and_not_automatically_driven():
    app, ids = reference()
    configure(app, ids)
    snapshot = app.create_branch_snapshot(ids["branch_id"])
    trial, run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 42)
    scoped = {**ids, "branch_id": trial.branch_id, "run_id": run.run_id}
    configure(app, scoped, paused=True)
    advance(app, scoped, 5)
    assert read_clock(app.states.get(ids["branch_id"])).seconds == 0
    assert read_clock(app.states.get(trial.branch_id)).seconds == 5
    assert WorldRunner(lambda: app).run_once(NOW + timedelta(days=1)) == 0


def api_command(admin, base, command, parameters, key):
    response = admin.post(
        "/api/v2/commands",
        json={**base, "command_type": command, "parameters": parameters, "idempotency_key": key},
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def clock_game(app, *, scope=None):
    admin, player, card, path, run, target, base = setup_scene(app, scope=scope)
    executor = admin.post(
        "/api/v2/actors",
        json={
            "world_id": base["world_id"],
            "display_name": "World clock",
            "kind": "AGENT",
            "roles": [],
            "capabilities": ["world.read", "action.propose", "action.commit"],
        },
    )
    assert executor.status_code == 201, executor.get_json()
    actor = executor.get_json()["actor_id"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 0,
            "executor_actor_id": actor,
            "wall_time": NOW.isoformat(),
        },
        "configure",
    )
    api_command(
        admin,
        base,
        "tabletop.activity.start",
        {
            "entity_id": target,
            "kind": "WEED",
            "duration_seconds": 100,
        },
        "gardening",
    )
    return admin, player, card, path, run, target, base


def test_api_player_cannot_manage_time_and_sees_only_inspected_activity(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    clock_path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"
    assert admin.get(clock_path).status_code == 200
    assert admin.get(clock_path).headers["Cache-Control"] == "no-store"
    assert player.get(clock_path).status_code == 403
    assert player.get(f"/api/v2/branches/{base['branch_id']}/replay").status_code == 403
    assert (
        player.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "tabletop.clock.advance",
                "parameters": {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 5},
                "idempotency_key": "forbidden",
            },
        ).status_code
        == 403
    )
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {
            "expected_epoch": 1,
            "expected_seconds": 0,
            "to_seconds": 5,
        },
        "five",
    )
    scene = player.get(path + "/scene").get_json()
    visible = next(row for row in scene["perceived_entities"] if row["entity_id"] == target)
    assert visible["activity"] == {
        "kind": "WEED",
        "status": "RUNNING",
        "progress_percent": 5,
        "weeded_units": 5,
    }
    serialized = str(scene)
    assert "next_due" not in serialized and "expected_epoch" not in serialized
    assert "activity_id" not in serialized and "executor_actor_id" not in serialized
    simulation = app.extensions["simulation"]
    simulation.states.get(uuid.UUID(base["branch_id"])).projections[
        "tabletop.sensory_profiles"
    ].setdefault(target, {})["invisible"] = True
    scene = player.get(path + "/scene").get_json()
    assert target not in {row["entity_id"] for row in scene["perceived_entities"]}


def test_character_and_world_runners_share_a_branch_without_stalling_offscreen_work(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    clock_path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"
    executor = admin.get(clock_path).get_json()["clock"]["executor_actor_id"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": executor,
            "wall_time": NOW.isoformat(),
            "paused": False,
            "seconds_per_tick": 2,
        },
        "resume-clock",
    )
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 4,
            "interval_ms": 100,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200, response.get_json()
    for second in (1, 2, 3):
        assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=second)) == 1
        assert app.extensions["character_runner"].run_once() == 1
        time.sleep(0.11)
    current = admin.get(clock_path).get_json()
    assert current["clock"]["seconds"] == 6
    assert current["activities"][target]["progress_seconds"] == 6
    assert player.get(path + "/control?run_id=" + run).get_json()["control"]["step"] == 3
    assert app.extensions["character_runner"].run_once() == 0
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=4)) == 1
    controller = app.extensions["controllers"].due()[0]
    pending = app.extensions["character_decisions"].decide(
        controller.scope, controller.executor_actor_id, "captured-before-pause", controller
    )
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {"expected_epoch": 2, "executor_actor_id": executor, "wall_time": NOW.isoformat()},
        "pause-world",
    )
    with pytest.raises(AuthorizationDenied, match="world clock is paused"):
        app.extensions["simulation"].submit(pending.outcome.proposal)
    assert app.extensions["character_runner"].run_once() == 0
    control = player.get(path + "/control?run_id=" + run).get_json()["control"]
    assert control["step"] == 3 and control["failures"] == 0
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 3,
            "executor_actor_id": executor,
            "wall_time": NOW.isoformat(),
            "paused": False,
        },
        "resume-world",
    )
    assert app.extensions["character_runner"].run_once() == 1


def pause_during_decision_and_resume(app, admin, player, path, run, base, monkeypatch):
    clock_path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"
    executor = admin.get(clock_path).get_json()["clock"]["executor_actor_id"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": executor,
            "wall_time": NOW.isoformat(),
            "paused": False,
        },
        "enable",
    )
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 2,
            "interval_ms": 100,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200, response.get_json()
    decisions = app.extensions["character_decisions"]
    original = decisions.decide

    def pause(*args, **kwargs):
        receipt = original(*args, **kwargs)
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {"expected_epoch": 2, "executor_actor_id": executor, "wall_time": NOW.isoformat()},
            "racing-pause",
        )
        return receipt

    # Restrict the durable scanner to this test's controller without bypassing its store.
    controllers = app.extensions["controllers"]
    due = controllers.due
    monkeypatch.setattr(
        controllers, "due", lambda: tuple(row for row in due() if str(row.run_id) == run)
    )
    monkeypatch.setattr(decisions, "decide", pause)
    assert app.extensions["character_runner"].run_once() == 0
    control = player.get(path + "/control?run_id=" + run).get_json()["control"]
    assert control["mode"] == "AUTONOMOUS" and control["step"] == 0 and control["failures"] == 0
    monkeypatch.setattr(decisions, "decide", original)
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 3,
            "executor_actor_id": executor,
            "wall_time": NOW.isoformat(),
            "paused": False,
        },
        "resume-after-race",
    )
    assert app.extensions["character_runner"].run_once() == 1
    control = player.get(path + "/control?run_id=" + run).get_json()["control"]
    assert control["mode"] == "AUTONOMOUS" and control["step"] == 1 and control["failures"] == 0


def test_clock_pause_during_character_decision_is_expected_suspension(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    pause_during_decision_and_resume(app, admin, player, path, run, base, monkeypatch)
