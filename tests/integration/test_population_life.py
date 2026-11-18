from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest

from kernel.api.app import create_app
from kernel.errors import BodySleeping
from tests.integration.test_population_runtime import runtime_path
from tests.integration.test_world_time import clock_path, prepare
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_world_time import NOW, api_command
from tests.unit.population.test_life import configure_game_life, game_meeting

pytestmark = pytest.mark.integration


def test_atomic_travel_sleep_and_social_state_survive_restart_and_retry(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    configure_game_life(app, game)
    partner, identity = game_meeting(admin, base, target)
    before = admin.get(clock_path(base)).get_json(), admin.get(runtime_path(base)).get_json()
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions

    def fail(*args):
        raise RuntimeError("test physical schedule rollback")

    command = {
        **base,
        "command_type": "tabletop.clock.advance",
        "idempotency_key": "seventy",
        "parameters": {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 70},
    }
    repository._insert_perceptions = fail
    try:
        assert admin.post("/api/v2/commands", json=command).status_code == 500
    finally:
        repository._insert_perceptions = original
    assert (
        admin.get(clock_path(base)).get_json(),
        admin.get(runtime_path(base)).get_json(),
    ) == before
    accepted = admin.post("/api/v2/commands", json=command)
    assert accepted.status_code == 200, accepted.get_json()
    assert admin.post("/api/v2/commands", json=command).get_json() == accepted.get_json()
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    current = restored.get(clock_path(base)).get_json()
    assert current["activities"][target]["kind"] == "TRAVEL"
    assert current["activities"][target]["due_seconds"] == 80
    assert current["activities"][target]["outputs"]["travel_steps"] == 1
    arrival = api_command(
        restored,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 70, "to_seconds": 90},
        "sleep",
    )
    records = arrival["event"]["payload"]["activity_records"]
    journey = next(item for item in records if item["kind"] == "TRAVEL")
    assert journey["status"] == "COMPLETED" and journey["due_seconds"] == 80
    assert journey["outputs"]["travel_steps"] == 2
    sleep = restored.get(clock_path(base)).get_json()["activities"][target]
    assert sleep["kind"] == "SLEEP" and sleep["due_seconds"] == 120
    assert sleep["outputs"]["sleep_seconds"] == 10
    api_command(
        restored,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 90, "to_seconds": 260},
        "finish",
    )
    current = restored.get(runtime_path(base)).get_json()
    assert current["obligations"][identity]["completed_count"] == 1
    visible = next(
        row
        for row in player.get(path + "/scene").get_json()["perceived_entities"]
        if row["entity_id"] == target
    )
    assert visible["activity"]["weeded_units"] == 90 and visible["position"]["x"] == 1
    replay = restored.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]
    body = replay["projections"]["tabletop.entities"][target]
    assert (
        body["sleep_seconds"] == 40 and body["social_seconds"] == 20 and body["travel_steps"] == 8
    )
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log c JOIN sim.events e "
            "USING(world_id,branch_id,run_id,actor_id,idempotency_key) "
            "JOIN sim.outbox o ON o.event_id=e.event_id "
            "WHERE c.run_id=%s AND c.idempotency_key='seventy'",
            (run,),
        )
        assert cursor.fetchone()[0] == 1


def test_two_actual_workers_and_restart_preserve_commutes_and_sleep(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    configure_game_life(app, game)
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
            f"run:{epoch}",
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
                value = admin.get(clock_path(base)).get_json()
                if value["clock"]["seconds"] == until:
                    assert value["clock"]["paused"]
                    return value
                assert all(child.poll() is None for child in children)
                time.sleep(0.1)
            pytest.fail("world workers did not reach finite life boundary")
        finally:
            for child in children:
                child.terminate()
            for child in children:
                child.wait(timeout=10)

    first = workers(1, 70, 2)
    assert first["activities"][target]["kind"] == "TRAVEL"
    second = workers(2, 160, 1)
    assert second["activities"][target]["progress_seconds"] == 80
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]
    physical = replay["projections"]["tabletop.entities"][target]
    assert physical["travel_steps"] == 4 and physical["sleep_seconds"] == 40


def test_recurring_appointments_privacy_world_scope_and_cancel(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    configure_game_life(app, game)
    partner, identity = game_meeting(admin, base, target, repeat=600)
    assert player.get(runtime_path(base)).status_code == 403
    other = admin.post("/api/v2/worlds", json={"name": "Foreign " + uuid.uuid4().hex}).get_json()
    bad = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.obligation.schedule",
            "idempotency_key": "foreign",
            "parameters": {
                "participants": [target, other["world_id"]],
                "place": {"x": 3, "y": 0},
                "starts_seconds": 200,
            },
        },
    )
    assert bad.status_code == 400
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 210},
        "meeting-in-progress",
    )
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.spatial.move",
            "idempotency_key": "look-closer",
            "parameters": {"dx": 1, "dy": 0},
        },
    )
    assert response.status_code == 200, response.get_json()
    scene = player.get(path + "/scene").get_json()
    visible = next(row for row in scene["perceived_entities"] if row["entity_id"] == target)
    assert visible["activity"]["kind"] == "SOCIAL" and visible["activity"]["progress_percent"] == 0
    for private in (
        "obligation_id",
        "starts_seconds",
        "awake_until",
        "workplace",
        "home",
        "suspended",
        "PRIVATE_GARDEN_HISTORY",
    ):
        assert private not in str(scene)
    context = player.get(path + "/context", query_string={"run_id": run})
    assert context.status_code == 200
    assert identity not in str(context.get_json()) and "PRIVATE_GARDEN_HISTORY" not in str(
        context.get_json()
    )
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 210, "to_seconds": 830},
        "next-occurrence",
    )
    row = admin.get(runtime_path(base)).get_json()["obligations"][identity]
    assert row["completed_count"] == 2 and row["occurrence"] == 1
    api_command(
        admin,
        base,
        "tabletop.obligation.cancel",
        {"obligation_id": identity, "expected_occurrence": 1},
        "cancel",
    )
    assert (
        admin.get(runtime_path(base)).get_json()["obligations"][identity]["status"] == "CANCELLED"
    )


def test_sleep_fences_captured_character_policy_and_human_input_wakes(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    api_command(
        admin,
        base,
        "tabletop.activity.start",
        {"entity_id": card["entity_id"], "kind": "REST"},
        "manual-rest",
    )
    seed_routine(app, admin, base, card["entity_id"])
    api_command(
        admin,
        base,
        "tabletop.routine.configure",
        {
            "entity_id": card["entity_id"],
            "expected_version": 1,
            "life": {
                "home": {"x": 0, "y": 0},
                "workplace": {"x": 0, "y": 0},
                "sleep_start_seconds": 10,
                "sleep_seconds": 60,
            },
        },
        "self-life",
    )
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
            "seconds_per_tick": 20,
        },
        "resume",
    )
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 2,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200, response.get_json()
    controller = app.extensions["controllers"].due()[0]
    pending = app.extensions["character_decisions"].decide(
        controller.scope, controller.executor_actor_id, "captured-before-sleep", controller
    )
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=1)) == 1
    with pytest.raises(BodySleeping):
        app.extensions["world_runner"].snapshot().submit(pending.outcome.proposal)
    assert app.extensions["character_runner"].run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["step"] == 0 and control["failures"] == 0 and control["mode"] == "AUTONOMOUS"
    response = player.post(
        path + "/control",
        json={"run_id": run, "mode": "HUMAN", "expected_epoch": 1, "idempotency_key": "takeover"},
    )
    assert response.status_code == 200, response.get_json()
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "control_epoch": 2,
            "command_type": "tabletop.spatial.move",
            "idempotency_key": "wake",
            "parameters": {"dx": 0, "dy": 1},
        },
    )
    assert response.status_code == 200, response.get_json()
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert not replay["projections"]["tabletop.entities"][card["entity_id"]]["asleep"]


def test_sleeping_npc_cannot_learn_ambient_speech_and_actual_damage_wakes_it(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = game
    configure_game_life(app, game)
    from tests.unit.kernel.test_tactical_choices import resources

    resources(app, admin, base, card["entity_id"], hp=12, mana=8)
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 90},
        "sleep",
    )
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.dialogue.speak",
            "parameters": {"text": "A quiet conversation."},
            "idempotency_key": "quiet-while-sleeping",
        },
    )
    assert response.status_code == 200, response.get_json()
    event = response.get_json()["event"]["event_id"]
    perceptions = admin.get(f"/api/v2/events/{event}/perceptions").get_json()["perceptions"]
    assert target not in {grant["observer_entity_id"] for grant in perceptions}
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.magic.invoke",
            "parameters": {"spell_id": "ARCANE_BOLT", "target_id": target},
            "idempotency_key": "wake-with-damage",
        },
    )
    assert response.status_code == 200, response.get_json()
    assert all(
        delta["projection"] != "tabletop.routines"
        for delta in response.get_json()["result"]["deltas"]
    )
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"] and not replay["projections"]["tabletop.entities"][target]["asleep"]
    assert replay["projections"]["tabletop.entities"][target]["hp"] == 97
    old = admin.get(f"/api/v2/events/{event}/perceptions").get_json()["perceptions"]
    assert target not in {grant["observer_entity_id"] for grant in old}
