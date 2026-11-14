from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from kernel.database import transaction
from kernel.errors import AuthorizationDenied
from tests.unit.kernel.test_world_time import (
    NOW,
    api_command,
    clock_game,
    pause_during_decision_and_resume,
)

pytestmark = pytest.mark.integration


def prepare(stack, monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    scope = admin.post("/api/v2/worlds", json={"name": "Clock " + uuid.uuid4().hex}).get_json()
    return app, clock_game(app, scope=scope)


def clock_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"


def test_two_stale_workers_one_tick_and_pause_fences_old_work(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    initial = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": initial["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": False,
            "seconds_per_tick": 10,
        },
        "resume",
    )
    sources = [
        create_app(artifact_root=tmp_path).extensions["world_runner"].snapshot() for _ in range(2)
    ]
    proposal = CommandProposal(
        **base,
        actor_id=uuid.UUID(initial["executor_actor_id"]),
        command_type="tabletop.clock.tick",
        idempotency_key="raced-tick",
        parameters={"epoch": 2, "step": 0, "wall_time": (NOW + timedelta(seconds=10)).isoformat()},
    )
    with ThreadPoolExecutor(max_workers=2) as workers:
        receipts = list(workers.map(lambda source: source.submit(proposal), sources))
    assert receipts[0].event.event_id == receipts[1].event.event_id
    current = admin.get(clock_path(base)).get_json()
    assert current["clock"]["seconds"] == 10
    assert current["activities"][target]["progress_seconds"] == 10
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 2,
            "executor_actor_id": initial["executor_actor_id"],
            "wall_time": NOW.isoformat(),
        },
        "pause",
    )
    assert sources[0].submit(proposal).event.event_id == receipts[0].event.event_id
    with pytest.raises(ValueError):
        sources[1].submit(proposal.model_copy(update={"idempotency_key": "stale-after-pause"}))
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 10
    assert player.get(clock_path(base)).status_code == 403
    assert player.get(f"/api/v2/branches/{base['branch_id']}/replay").status_code == 403
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log "
            "WHERE run_id=%s AND command_type='tabletop.clock.tick'",
            (run,),
        )
        assert cursor.fetchone()[0] == 1


def test_failed_ledger_write_rolls_back_clock_work_and_weather_then_retries_once(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    for due, rain in ((30, True), (70, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"due_seconds": due, "zone_id": "world", "raining": rain},
            f"weather{due}",
        )
    before = admin.get(clock_path(base)).get_json()
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions

    def fail(*args):
        raise RuntimeError("test ledger rollback")

    repository._insert_perceptions = fail
    payload = {
        **base,
        "command_type": "tabletop.clock.advance",
        "idempotency_key": "hundred",
        "parameters": {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 100},
    }
    try:
        assert admin.post("/api/v2/commands", json=payload).status_code == 500
    finally:
        repository._insert_perceptions = original
    assert admin.get(clock_path(base)).get_json() == before
    accepted = admin.post("/api/v2/commands", json=payload)
    assert accepted.status_code == 200, accepted.get_json()
    assert admin.post("/api/v2/commands", json=payload).get_json() == accepted.get_json()
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    current = restored.get(clock_path(base)).get_json()
    assert (
        current["clock"]["seconds"] == 100
        and current["activities"][target]["progress_seconds"] == 60
    )
    assert not current["pending_weather"]
    scene = player.get(path + "/scene").get_json()
    assert (
        next(row for row in scene["perceived_entities"] if row["entity_id"] == target)["activity"][
            "weeded_units"
        ]
        == 60
    )
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log c JOIN sim.events e ON "
            "(c.run_id,c.actor_id,c.idempotency_key)=(e.run_id,e.actor_id,e.idempotency_key) "
            "JOIN sim.outbox o ON o.event_id=e.event_id "
            "WHERE c.run_id=%s AND c.idempotency_key='hundred'",
            (run,),
        )
        assert cursor.fetchone()[0] == 1


def test_scope_rls_and_executor_revocation_recheck_live_database(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    clock = admin.get(clock_path(base)).get_json()["clock"]
    other = admin.post(
        "/api/v2/worlds", json={"name": "Foreign clock " + uuid.uuid4().hex}
    ).get_json()
    agent = admin.post(
        "/api/v2/actors",
        json={
            "world_id": other["world_id"],
            "display_name": "Foreign",
            "kind": "AGENT",
            "roles": [],
            "capabilities": ["world.read", "action.propose", "action.commit"],
        },
    ).get_json()["actor_id"]
    with (
        transaction(actor_id=uuid.UUID(agent), dsn=integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT state FROM sim.branch_projections WHERE world_id=%s AND branch_id=%s",
            (base["world_id"], base["branch_id"]),
        )
        assert cursor.fetchall() == []
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.clock.configure",
            "idempotency_key": "foreign-executor",
            "parameters": {
                "expected_epoch": 1,
                "executor_actor_id": agent,
                "wall_time": NOW.isoformat(),
            },
        },
    )
    assert response.status_code == 403
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": False,
        },
        "resume",
    )
    stale = app.extensions["world_runner"].snapshot()
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM sim.actor_capabilities "
            "WHERE world_id=%s AND actor_id=%s AND capability='action.commit'",
            (base["world_id"], clock["executor_actor_id"]),
        )
    with pytest.raises(AuthorizationDenied):
        stale.submit(
            CommandProposal(
                **base,
                actor_id=uuid.UUID(clock["executor_actor_id"]),
                command_type="tabletop.clock.tick",
                idempotency_key="revoked",
                parameters={
                    "epoch": 2,
                    "step": 0,
                    "wall_time": (NOW + timedelta(seconds=2)).isoformat(),
                },
            )
        )
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 0


def test_actual_world_runner_processes_continue_without_viewers_and_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    initial = admin.get(clock_path(base)).get_json()["clock"]

    def enable(epoch, until, key):
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": epoch,
                "executor_actor_id": initial["executor_actor_id"],
                "wall_time": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                "paused": False,
                "seconds_per_tick": 3,
                "until_seconds": until,
            },
            key,
        )

    def workers_until(until, count):
        processes = [
            subprocess.Popen(
                [sys.executable, "main.py", "world-runner"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(count)
        ]
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                current = admin.get(clock_path(base)).get_json()
                if current["clock"]["seconds"] == until:
                    assert current["clock"]["paused"]
                    return current
                assert all(process.poll() is None for process in processes), "world runner exited"
                time.sleep(0.1)
            pytest.fail("world runner did not reach its configured boundary")
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=10)

    enable(1, 6, "start-processes")
    # A human action shares the branch with independent world progression.
    moved = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.spatial.move",
            "parameters": {"dx": 0, "dy": 1},
            "idempotency_key": "human-move",
        },
    )
    assert moved.status_code == 200, moved.get_json()
    first = workers_until(6, 2)
    assert first["activities"][target]["progress_seconds"] == 6
    enable(2, 9, "resume-process")
    second = workers_until(9, 1)
    assert second["activities"][target]["progress_seconds"] == 9
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]
    assert replay["projections"]["tabletop.clock"]["singleton"]["seconds"] == 9
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log "
            "WHERE run_id=%s AND command_type='tabletop.clock.tick'",
            (run,),
        )
        assert cursor.fetchone()[0] == 3


def test_clock_pause_fences_captured_character_action_inside_durable_lock(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
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
            "interval_ms": 100,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200, response.get_json()
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    controller = next(row for row in app.extensions["controllers"].due() if str(row.run_id) == run)
    pending = app.extensions["character_decisions"].decide(
        controller.scope, controller.executor_actor_id, "captured", controller
    )
    stale = app.extensions["world_runner"].snapshot()
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 2,
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
        },
        "pause",
    )
    with pytest.raises(AuthorizationDenied, match="world clock is paused"):
        stale.submit(pending.outcome.proposal)
    control = player.get(path + "/control?run_id=" + run).get_json()["control"]
    assert control["step"] == 0 and control["failures"] == 0


def test_pause_during_actual_character_runner_preserves_resume_without_handoff(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    pause_during_decision_and_resume(app, admin, player, path, run, base, monkeypatch)
