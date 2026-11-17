from __future__ import annotations

import time
from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest

from kernel.control import ControllerState
from kernel.errors import BodyOutsideRelevance
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_npc_goals import clock_path, configure_subjective
from tests.unit.kernel.test_world_time import NOW, api_command, clock_game

pytestmark = pytest.mark.unit


def check_population_resolution(app, game, restart, monkeypatch):
    game, _, npc_path, _, configured = configure_subjective(app, game)
    admin, player, card, _, run, target, base = game
    config = deepcopy(configured)
    config.update(expected_version=2, relevance_radius=1, relevance_anchors=[card["entity_id"]])
    planning = config["life"]["planning"]
    planning.update(motivated=False, goals=planning["goals"][:1])
    api_command(admin, base, "tabletop.routine.configure", config, "garden-relevance")

    def set_clock(*, paused, key):
        clock = admin.get(clock_path(base)).get_json()["clock"]
        return api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": clock["epoch"],
                "executor_actor_id": clock["executor_actor_id"],
                "paused": paused,
                "wall_time": NOW.isoformat(),
                "offline_policy": "CATCH_UP",
                "max_catch_up_ticks": 60,
            },
            key,
        )

    set_clock(paused=False, key="resume-garden")

    def move_party(dx, key):
        return api_command(
            player,
            {**base, "embodied_entity_id": card["entity_id"]},
            "tabletop.spatial.move",
            {"dx": dx, "dy": 0},
            key,
        )

    move_party(-1, "leave-first")
    control = admin.post(
        npc_path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 2,
            "interval_ms": 60000,
            "idempotency_key": "garden-autonomy",
        },
    )
    assert control.status_code == 200, control.get_json()
    initial = ControllerState.model_validate(control.get_json()["state"])

    worker = restart()
    runner = worker.extensions["character_runner"]
    controls = worker.extensions["controllers"]
    other_due = controls.due
    monkeypatch.setattr(
        controls, "due", lambda: tuple(row for row in other_due() if str(row.run_id) == run)
    )

    def current_control():
        return ControllerState.model_validate(
            admin.get(npc_path + "/control", query_string={"run_id": run}).get_json()["control"]
        )

    def tick_to(seconds):
        worker.extensions["world_runner"].run_once(NOW + timedelta(seconds=seconds))
        assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == seconds

    assert runner.run_once() == 0
    deferred = current_control()
    assert deferred.next_due > initial.next_due
    assert deferred.model_dump(exclude={"next_due"}) == initial.model_dump(exclude={"next_due"})

    tick_to(20)
    progress = admin.get(clock_path(base)).get_json()["activities"][target]
    assert progress["kind"] == "WEED" and progress["progress_seconds"] == 20
    move_party(1, "return-first")

    deadline = time.monotonic() + 5
    while not (due := controls.due()):
        assert time.monotonic() < deadline, "relevant NPC controller did not become due"
        time.sleep(0.02)
    assert len(due) == 1
    controller = due[0]
    decision = worker.extensions["character_decisions"].decide(
        controller.scope,
        controller.executor_actor_id,
        f"controller:{controller.epoch}:step:{controller.step}",
        controller,
    )

    tick_to(21)
    move_party(-1, "leave-before-action")
    branch = UUID(base["branch_id"])
    before = runner.snapshot().states.get(branch).state_hash
    with pytest.raises(BodyOutsideRelevance):
        runner.snapshot().submit(decision.outcome.proposal)
    assert runner.snapshot().states.get(branch).state_hash == before
    assert current_control().step == 0

    tick_to(22)
    move_party(1, "return-for-action")
    assert runner.run_once() == 1
    committed = runner.snapshot().states.get(branch).state_hash
    assert runner.snapshot().submit(decision.outcome.proposal).result.accepted
    assert runner.snapshot().states.get(branch).state_hash == committed
    assert runner.run_once() == 0
    finished = current_control()
    assert finished.step == 1
    stopped = admin.post(
        npc_path + "/control",
        json={
            "run_id": run,
            "mode": "PAUSED",
            "expected_epoch": finished.epoch,
            "idempotency_key": "pause-garden-controller",
        },
    )
    assert stopped.status_code == 200, stopped.get_json()
    set_clock(paused=True, key="pause-garden-clock")


def test_offscreen_routine_yields_to_detailed_actions_when_party_returns(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    check_population_resolution(app, clock_game(app), lambda: app, monkeypatch)
