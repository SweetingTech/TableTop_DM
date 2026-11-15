from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest

from kernel.api.app import create_app
from tests.integration.test_population_runtime import runtime_path
from tests.integration.test_world_time import clock_path, prepare
from tests.unit.kernel.test_world_time import api_command
from tests.unit.population.test_planning import configure_game_plan

pytestmark = pytest.mark.integration


def test_planning_quota_and_shelter_rollback_retry_restart_and_privacy(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    config = configure_game_plan(app, game)
    for due, raining in ((40, True), (100, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"zone_id": "world", "due_seconds": due, "raining": raining},
            f"rain:{due}",
        )
    before = admin.get(runtime_path(base)).get_json(), admin.get(clock_path(base)).get_json()
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions

    def fail(*args):
        raise RuntimeError("test planner atomic rollback")

    proposal = {
        **base,
        "command_type": "tabletop.clock.advance",
        "idempotency_key": "daily-fifty",
        "parameters": {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 50},
    }
    repository._insert_perceptions = fail
    try:
        assert admin.post("/api/v2/commands", json=proposal).status_code == 500
    finally:
        repository._insert_perceptions = original
    assert (
        admin.get(runtime_path(base)).get_json(),
        admin.get(clock_path(base)).get_json(),
    ) == before
    first = admin.post("/api/v2/commands", json=proposal)
    assert first.status_code == 200, first.get_json()
    assert admin.post("/api/v2/commands", json=proposal).get_json() == first.get_json()
    current = admin.get(runtime_path(base)).get_json()
    assert current["routines"][target]["planner"]["spent"]["private_garden_goal"] == 40
    restored = create_app(artifact_root=tmp_path).test_client()
    restored.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    api_command(
        restored,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 50, "to_seconds": 300},
        "finish-day",
    )
    current = restored.get(runtime_path(base)).get_json()
    row = current["routines"][target]
    assert row["planner"]["spent"] == {"private_garden_goal": 120, "private_reading_goal": 60}
    replay = restored.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]
    assert replay["projections"]["tabletop.entities"][target]["weeded_units"] == 120
    assert player.get(runtime_path(base)).status_code == 403
    denied = player.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.routine.configure",
            "idempotency_key": "player-planner",
            "parameters": {**config, "expected_version": 3},
        },
    )
    assert denied.status_code == 403
    scene = player.get(path + "/scene").get_json()
    for private in (
        "private_garden_goal",
        "private_reading_goal",
        "planner",
        "seconds_per_day",
        "decision_sequence",
        "PRIVATE_GARDEN_HISTORY",
    ):
        assert private not in str(scene)
    foreign = {
        **config,
        "expected_version": 3,
        "life": {**config["life"], "home": {"x": 3, "y": 0, "zone_id": "foreign"}},
    }
    bad = restored.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.routine.configure",
            "idempotency_key": "bad-plan",
            "parameters": foreign,
        },
    )
    assert bad.status_code == 400
    assert restored.get(runtime_path(base)).get_json() == current


def test_two_world_workers_and_restart_finish_daily_choices_once(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    configure_game_plan(app, game)
    for due, raining in ((40, True), (100, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"zone_id": "world", "due_seconds": due, "raining": raining},
            f"rain:{due}",
        )
    clock = admin.get(clock_path(base)).get_json()["clock"]

    def workers(epoch, until, count):
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": epoch,
                "executor_actor_id": clock["executor_actor_id"],
                "seconds_per_tick": 30,
                "until_seconds": until,
                "paused": False,
                "wall_time": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            f"start:{epoch}",
        )
        children = [
            subprocess.Popen(
                [sys.executable, "main.py", "world-runner"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(count)
        ]
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                current = admin.get(clock_path(base)).get_json()
                if current["clock"]["seconds"] == until:
                    assert current["clock"]["paused"]
                    return current
                assert all(child.poll() is None for child in children)
                time.sleep(0.1)
            pytest.fail("daily-planning worker did not reach finite boundary")
        finally:
            for child in children:
                child.terminate()
            for child in children:
                child.wait(timeout=10)

    first = workers(1, 50, 2)
    assert first["activities"][target]["kind"] == "TRAVEL"
    workers(2, 300, 1)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert row["planner"]["spent"] == {"private_garden_goal": 120, "private_reading_goal": 60}
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]
    assert replay["projections"]["tabletop.entities"][target]["weeded_units"] == 120
