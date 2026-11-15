from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from cognition.store import MindStore
from domains.tabletop.action_time import ACTION_TIME
from domains.tabletop.character_actions import character_action_candidates
from domains.tabletop.spatial.service import build_perceived_scene
from kernel.contracts import CommandProposal
from kernel.errors import BodyActionPending
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import NOW, api_command, clock_game

pytestmark = pytest.mark.unit


def clock_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"


def advance_clock(admin, base, until):
    clock = admin.get(clock_path(base)).get_json()["clock"]
    return api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {
            "expected_epoch": clock["epoch"],
            "expected_seconds": clock["seconds"],
            "to_seconds": until,
        },
        f"timing-advance-{until}",
    )


def test_cost_retry_invalid_action_and_guard_expiry_are_atomic(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    first = command(player, base, card, "tabletop.combat.guard", {}, "guard")
    assert first.status_code == 200, first.get_json()
    row = state.projections[ACTION_TIME][card["entity_id"]]
    assert row["duration_seconds"] == row["ready_seconds"] == 6
    original = state.state_hash, state.version
    for kind, parameters in [
        ("tabletop.spatial.move", {"dx": 1, "dy": 0}),
        ("tabletop.magic.invoke", {"spell_id": "MEND", "target_id": card["entity_id"]}),
    ]:
        denied = command(player, base, card, kind, parameters, "too-early-" + kind)
        assert denied.status_code == 400
        assert (state.state_hash, state.version) == original
    assert (
        command(player, base, card, "tabletop.combat.guard", {}, "guard").get_json()
        == first.get_json()
    )
    assert (state.state_hash, state.version) == original
    advance_clock(admin, base, 5)
    assert state.projections["tabletop.entities"][card["entity_id"]]["guarded"]
    advance_clock(admin, base, 6)
    assert not state.projections["tabletop.entities"][card["entity_id"]]["guarded"]
    original = state.state_hash, state.version
    assert (
        command(
            player, base, card, "tabletop.spatial.move", {"dx": 0, "dy": 0}, "invalid"
        ).status_code
        == 400
    )
    assert (state.state_hash, state.version) == original
    assert (
        command(player, base, card, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "move").status_code
        == 200
    )
    assert state.projections[ACTION_TIME][card["entity_id"]]["ready_seconds"] == 7
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 6


def test_speech_does_not_spend_or_replace_physical_action_time(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    assert command(player, base, card, "tabletop.combat.guard", {}, "guard").status_code == 200
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    reservation = dict(state.projections[ACTION_TIME][card["entity_id"]])
    for index in range(2):
        assert (
            command(
                player,
                base,
                card,
                "tabletop.dialogue.speak",
                {"text": "Stay calm."},
                f"say-{index}",
            ).status_code
            == 200
        )
        assert state.projections[ACTION_TIME][card["entity_id"]] == reservation


@pytest.mark.parametrize("speed,seconds", [(30, 1), (15, 2), (5, 6), (0, None)])
def test_movement_uses_body_speed_and_cannot_override_duration(
    monkeypatch, tmp_path, speed, seconds
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    state.projections["tabletop.entities"][card["entity_id"]]["speed"] = speed
    before = state.state_hash, state.version
    response = command(
        player,
        base,
        card,
        "tabletop.spatial.move",
        {
            "dx": 1,
            "dy": 0,
            "duration_seconds": 0,
            "ready_seconds": 0,
        },
        "move",
    )
    if seconds is None:
        assert response.status_code == 400
        assert (state.state_hash, state.version) == before
    else:
        assert response.status_code == 200, response.get_json()
        assert state.projections[ACTION_TIME][card["entity_id"]]["ready_seconds"] == seconds


def test_concurrent_distinct_commands_reserve_one_body_once(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    sim = app.extensions["simulation"]
    actor = sim.entities[
        (uuid.UUID(base["branch_id"]), uuid.UUID(card["entity_id"]))
    ].controller_actor_id
    request = CommandProposal(
        **base,
        actor_id=actor,
        embodied_entity_id=card["entity_id"],
        command_type="tabletop.spatial.move",
        parameters={"dx": 1, "dy": 0},
        idempotency_key="race",
    )

    def attempt(index):
        try:
            sim.submit(
                request.model_copy(
                    update={"command_id": uuid.uuid4(), "idempotency_key": f"race-{index}"}
                )
            )
            return "committed"
        except BodyActionPending:
            return "waiting"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(attempt, range(2))) == ["committed", "waiting"]
    state = sim.states.get(request.branch_id)
    assert state.projections["tabletop.entities"][card["entity_id"]]["x"] == 1


def test_wait_is_self_only_and_suppresses_impossible_candidates(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    assert command(player, base, card, "tabletop.combat.guard", {}, "guard").status_code == 200
    sim = app.extensions["simulation"]
    scene = player.get(path + "/scene").get_json()
    assert (
        next(row for row in scene["perceived_entities"] if row["entity_id"] == card["entity_id"])[
            "action_wait_seconds"
        ]
        == 6
    )
    assert all(
        row["action_wait_seconds"] is None
        for row in scene["perceived_entities"]
        if row["entity_id"] != card["entity_id"]
    )
    state = sim.states.get(uuid.UUID(base["branch_id"]))
    actor = sim.entities[(state.branch_id, uuid.UUID(card["entity_id"]))].controller_actor_id
    perceived = build_perceived_scene(
        sim,
        MindStore(),
        world_id=state.world_id,
        branch_id=state.branch_id,
        observer_entity_id=uuid.UUID(card["entity_id"]),
        actor_id=actor,
    )
    assert (
        character_action_candidates(
            perceived, actor=sim.authority(state.world_id, actor), branch_kind=state.kind
        )
        == ()
    )


def test_runner_wait_preserves_budget_and_resumes_on_clock(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
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
            "seconds_per_tick": 6,
        },
        "resume",
    )
    assert command(player, base, card, "tabletop.combat.guard", {}, "guard").status_code == 200
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
    runner = app.extensions["character_runner"]
    for _ in range(4):
        assert runner.run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["step"] == control["failures"] == 0 and control["mode"] == "AUTONOMOUS"
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=1)) == 1
    assert runner.run_once() == 1


def test_new_wait_during_decision_is_expected_suspension(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
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
            "seconds_per_tick": 6,
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
    runner = app.extensions["character_runner"]
    original = runner.decisions.decide

    def reserve_during_decision(*args, **kwargs):
        result = original(*args, **kwargs)
        # Inject the already-committed state seen at the kernel race boundary.
        state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
        state.projections.setdefault(ACTION_TIME, {})[card["entity_id"]] = {"ready_seconds": 6}
        return result

    monkeypatch.setattr(runner.decisions, "decide", reserve_during_decision)
    assert runner.run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["step"] == control["failures"] == 0 and control["mode"] == "AUTONOMOUS"
    monkeypatch.setattr(runner.decisions, "decide", original)
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=1)) == 1
    assert runner.run_once() == 1


def test_trial_inherits_physical_wait_but_advances_independently(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    assert command(player, base, card, "tabletop.combat.guard", {}, "guard").status_code == 200
    sim = app.extensions["simulation"]
    branch = uuid.UUID(base["branch_id"])
    snapshot = sim.create_branch_snapshot(branch)
    trial, trial_run = sim.create_trial(uuid.UUID(base["world_id"]), snapshot.snapshot_id, 7)
    trial_base = {**base, "branch_id": str(trial.branch_id), "run_id": str(trial_run.run_id)}
    assert (
        command(
            player, trial_base, card, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "old-clock"
        ).status_code
        == 400
    )
    clock = admin.get(clock_path(trial_base)).get_json()["clock"]
    api_command(
        admin,
        trial_base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
        },
        "trial-clock",
    )
    advance_clock(admin, trial_base, 6)
    assert (
        command(
            player, trial_base, card, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "trial-move"
        ).status_code
        == 200
    )
    assert sim.states.get(branch).projections["tabletop.entities"][card["entity_id"]]["guarded"]
    assert sim.states.get(branch).projections["tabletop.clock"]["singleton"]["seconds"] == 0
