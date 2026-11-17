from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import discover, migrate
from kernel.api.app import create_app
from population.runtime import MEMBERS
from tests.integration.test_world_time import clock_path, prepare
from tests.unit.kernel.test_population_resolution import check_population_resolution
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_speech_combat_behavior import setup_scene
from tests.unit.kernel.test_world_time import NOW, api_command

pytestmark = pytest.mark.integration


def runtime_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/population"


def test_durable_npc_resolution_uses_live_physical_relevance(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    check_population_resolution(
        app, game, lambda: create_app(artifact_root=tmp_path / "npc-worker"), monkeypatch
    )


def test_binding_rollback_retry_freeze_guards_and_source_validation(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    root, member_path, body = seed_routine(app, admin, base, target, bind=False)
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions

    def fail(*args):
        raise RuntimeError("test binding rollback")

    repository._insert_perceptions = fail
    try:
        assert admin.post(member_path + "/bind", json=body).status_code == 500
    finally:
        repository._insert_perceptions = original
    assert not admin.get(runtime_path(base)).get_json()["members"]
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT binding_event_id, entity_id FROM population.materialized_people "
            "WHERE population_id=%s",
            (root.rsplit("/", 1)[-1],),
        )
        assert cursor.fetchone() == (None, None)
        cursor.execute(
            "SELECT count(*) FROM sim.command_log WHERE run_id=%s "
            "AND command_type='tabletop.population.bind'",
            (run,),
        )
        assert cursor.fetchone()[0] == 0
    # A structurally valid but forged profile must fail the transactional source comparison.
    source = app.extensions["population_runtime"].source_reader(
        uuid.UUID(root.rsplit("/", 1)[-1]), uuid.UUID(member_path.rsplit("/", 1)[-1])
    )
    forged = source.model_copy(update={"profile": {"occupation_sector": "forged"}})
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.population.bind",
            "idempotency_key": "forged-source",
            "parameters": {
                "population_id": root.rsplit("/", 1)[-1],
                "entity_id": target,
                "source_member": forged.model_dump(mode="json"),
            },
        },
    )
    assert response.status_code == 400, response.get_json()
    assert not admin.get(runtime_path(base)).get_json()["members"]
    accepted = admin.post(member_path + "/bind", json=body)
    assert accepted.status_code == 200, accepted.get_json()
    assert admin.post(member_path + "/bind", json=body).get_json() == accepted.get_json()
    # Runtime grants remain least privilege; even direct stale writes cannot revive the source.
    for statement in (
        "UPDATE population.materialized_people SET persistent_state='{}'::jsonb "
        "WHERE population_id=%s",
        "UPDATE population.materialized_people SET binding_event_id=NULL,binding_source_hash=NULL "
        "WHERE population_id=%s",
        "INSERT INTO population.lifecycle_transitions SELECT gen_random_uuid(),population_id,"
        "world_id,branch_id,persona_id,sequence+100,lifecycle_version+100,from_level,to_level,"
        "reason,world_step,persistent_state_hash,active_state_hash,now() "
        "FROM population.lifecycle_transitions WHERE population_id=%s LIMIT 1",
    ):
        with pytest.raises(psycopg2.errors.CheckViolation):
            with (
                psycopg2.connect(integration_stack.database_url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(statement, (root.rsplit("/", 1)[-1],))
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT parameters::text FROM sim.command_log WHERE run_id=%s "
            "AND command_type='tabletop.population.bind'",
            (run,),
        )
        assert "PRIVATE_GARDEN_HISTORY" not in cursor.fetchone()[0]
        cursor.execute(
            "SELECT count(*) FROM sim.command_log c JOIN sim.events e "
            "USING(world_id,branch_id,run_id,actor_id,idempotency_key) "
            "JOIN sim.outbox o ON o.event_id=e.event_id WHERE c.run_id=%s "
            "AND c.command_type='tabletop.population.bind'",
            (run,),
        )
        assert cursor.fetchone()[0] == 1


def test_work_rain_lifecycle_and_needs_survive_restart_and_atomic_failure(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    root, member_path, body = seed_routine(app, admin, base, target)
    for due, rain in ((30, True), (90, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"due_seconds": due, "zone_id": "world", "raining": rain},
            f"rain{due}",
        )
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 40},
        "forty",
    )
    assert admin.get(clock_path(base)).get_json()["activities"][target]["progress_seconds"] == 30
    response = admin.post(member_path + "/activate", json={"active_state": {}, "world_step": 40})
    assert response.status_code == 200, response.get_json()
    assert admin.post(member_path + "/deactivate", json={"world_step": 40}).status_code == 200
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions
    before = admin.get(runtime_path(base)).get_json()
    before_clock = admin.get(clock_path(base)).get_json()

    def fail(*args):
        raise RuntimeError("test routine rollback")

    command = {
        **base,
        "command_type": "tabletop.clock.advance",
        "idempotency_key": "hundred",
        "parameters": {"expected_epoch": 1, "expected_seconds": 40, "to_seconds": 100},
    }
    repository._insert_perceptions = fail
    try:
        assert admin.post("/api/v2/commands", json=command).status_code == 500
    finally:
        repository._insert_perceptions = original
    assert admin.get(runtime_path(base)).get_json() == before
    assert admin.get(clock_path(base)).get_json() == before_clock
    accepted = admin.post("/api/v2/commands", json=command)
    assert accepted.status_code == 200, accepted.get_json()
    assert admin.post("/api/v2/commands", json=command).get_json() == accepted.get_json()
    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client()
    restored.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    assert restored.get(clock_path(base)).get_json()["activities"][target]["progress_seconds"] == 40
    assert restored.get(member_path).get_json()["persistent_state"] == {
        "memories": ["PRIVATE_GARDEN_HISTORY"]
    }
    # A newly composed API sees persisted needs and pauses at the actual food shortage.
    api_command(
        restored,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 100, "to_seconds": 310},
        "hungry",
    )
    assert restored.get(clock_path(base)).get_json()["activities"][target]["reason"] == "NO_FOOD"
    assert admin.get(clock_path(base)).get_json() == restored.get(clock_path(base)).get_json()
    scene = player.get(path + "/scene").get_json()
    assert "PRIVATE_GARDEN_HISTORY" not in str(scene) and "routine_id" not in str(scene)
    replay = restored.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]


def test_source_binding_constraints_and_branch_isolation(integration_stack, monkeypatch, tmp_path):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    root, member_path, body = seed_routine(app, admin, base, target, bind=False)
    pool = root.rsplit("/", 1)[-1]
    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT has_table_privilege(current_user,"
            "'population.materialized_people','SELECT,INSERT,UPDATE'),"
            "has_table_privilege(current_user,'population.materialized_people','DELETE'),"
            "has_function_privilege(current_user,'population.guard_embodied_source()',"
            "'EXECUTE')"
        )
        assert cursor.fetchone() == (True, False, False)
    with pytest.raises(psycopg2.errors.CheckViolation):
        with (
            psycopg2.connect(integration_stack.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE population.materialized_people SET binding_source_hash=%s "
                "WHERE population_id=%s",
                ("a" * 64, pool),
            )
    # Direct inserts/updates cannot invent a binding without a scoped committed event.
    with pytest.raises(psycopg2.errors.CheckViolation):
        with (
            psycopg2.connect(integration_stack.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE population.materialized_people "
                "SET entity_id=%s,binding_event_id=%s,binding_source_hash=%s "
                "WHERE population_id=%s",
                (target, str(uuid.uuid4()), "a" * 64, pool),
            )
    accepted = admin.post(member_path + "/bind", json=body)
    assert accepted.status_code == 200, accepted.get_json()
    other = admin.post(
        "/api/v2/worlds", json={"name": "Foreign village " + uuid.uuid4().hex}
    ).get_json()
    forbidden = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "world_id": other["world_id"],
            "command_type": "tabletop.routine.configure",
            "idempotency_key": "foreign-routine",
            "parameters": {"entity_id": target, "expected_version": 0},
        },
    )
    assert forbidden.status_code == 400
    source = app.extensions["population_runtime"].snapshot()
    current = source.states.get(uuid.UUID(base["branch_id"]))
    bad_promotion = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "kernel.branch.promote",
            "idempotency_key": "erase-binding",
            "parameters": {
                "source_branch_id": base["branch_id"],
                "expected_canonical_hash": current.state_hash,
                "review_note": "Forbidden import removal",
                "deltas": [
                    {
                        "projection": MEMBERS,
                        "operation": "DELETE",
                        "entity_id": member_path.rsplit("/", 1)[-1],
                    }
                ],
            },
        },
    )
    assert bad_promotion.status_code == 400, bad_promotion.get_json()
    assert (
        app.extensions["population_runtime"]
        .snapshot()
        .states.get(uuid.UUID(base["branch_id"]))
        .state_hash
        == current.state_hash
    )
    # An actor with no world grant cannot read the canonical population projection through RLS.
    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT set_config('app.actor_id',%s,true)", (str(uuid.uuid4()),))
        cursor.execute(
            "SELECT state FROM sim.branch_projections WHERE world_id=%s AND branch_id=%s",
            (base["world_id"], base["branch_id"]),
        )
        assert cursor.fetchall() == []


def test_two_actual_world_workers_and_restart_do_not_reset_or_double_award_routines(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    root, member_path, body = seed_routine(app, admin, base, target)
    api_command(
        admin,
        base,
        "tabletop.routine.configure",
        {
            "entity_id": target,
            "expected_version": 1,
            "work_seconds": 120,
            "rest_seconds": 60,
            "relevance_radius": 1,
            "relevance_anchors": [card["entity_id"]],
        },
        "party-relevance",
    )
    for due, raining in ((45, True), (75, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"due_seconds": due, "zone_id": "world", "raining": raining},
            f"rain:{due}",
        )
    initial = admin.get(clock_path(base)).get_json()["clock"]

    def advance_in_processes(epoch, until, count):
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": epoch,
                "executor_actor_id": initial["executor_actor_id"],
                "wall_time": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                "paused": False,
                "seconds_per_tick": 30,
                "until_seconds": until,
            },
            f"processes:{epoch}",
        )
        processes = [
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
                assert all(process.poll() is None for process in processes)
                time.sleep(0.1)
            pytest.fail("routine worker did not reach its finite clock boundary")
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=10)

    first = advance_in_processes(1, 30, 2)
    assert first["activities"][target]["progress_seconds"] == 30
    assert admin.get(member_path).get_json()["level"] == "ACTIVE"
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.spatial.move",
            "parameters": {"dx": -1, "dy": 0},
            "idempotency_key": "party-leaves",
        },
    )
    assert response.status_code == 200, response.get_json()
    second = advance_in_processes(2, 60, 1)
    interrupted = second["activities"][target]
    assert interrupted["progress_seconds"] == 45
    assert interrupted["status"] == "WAITING" and interrupted["reason"] == "RAIN"
    assert admin.get(member_path).get_json()["level"] == "MATERIALIZED"
    resumed = advance_in_processes(3, 90, 1)
    assert resumed["activities"][target]["progress_seconds"] == 60
    assert resumed["activities"][target]["activity_id"] == interrupted["activity_id"]
    assert admin.get(member_path).get_json()["level"] == "MATERIALIZED"
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.spatial.move",
            "parameters": {"dx": 1, "dy": 0},
            "idempotency_key": "party-returns",
        },
    )
    assert response.status_code == 200, response.get_json()
    third = advance_in_processes(4, 105, 1)
    assert third["activities"][target]["progress_seconds"] == 75
    assert admin.get(member_path).get_json()["level"] == "ACTIVE"
    scene = player.get(path + "/scene").get_json()
    history = admin.get(root + "/transitions").get_json()
    assert [item["world_step"] for item in history] == [17, 17, 17, 47, 107]
    visible = next(row for row in scene["perceived_entities"] if row["entity_id"] == target)
    assert visible["position"]["x"] == 1 and visible["position"]["y"] == 0
    assert (
        next(row for row in scene["perceived_entities"] if row["entity_id"] == target)["activity"][
            "weeded_units"
        ]
        == 75
    )
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.command_log WHERE run_id=%s "
            "AND command_type='tabletop.clock.tick'",
            (run,),
        )
        assert cursor.fetchone()[0] == 4


def test_010_upgrade_preserves_materialized_source_and_can_bind_afterwards(
    integration_stack, monkeypatch, tmp_path
):
    name = "ttdm_population_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for migration in sorted(migrations.glob("*.sql"))[:10]:
            shutil.copy2(migration, prior / migration.name)
        assert migrate(url, prior) == 10
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
        app = create_app(artifact_root=tmp_path / "before")
        client = app.test_client()
        client.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
        scope = client.post("/api/v2/worlds", json={"name": "Population upgrade"}).get_json()
        admin, _, _, _, _, target, base = setup_scene(app, scope=scope)
        _, member_path, body = seed_routine(app, admin, base, target, bind=False)
        before = admin.get(member_path).get_json()
        assert migrate(url, migrations) == len(discover(migrations)) - 10
        assert migrate(url, migrations) == 0
        assert admin.get(member_path).get_json() == before
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
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": 0,
                "executor_actor_id": executor.get_json()["actor_id"],
                "wall_time": NOW.isoformat(),
            },
            "configure",
        )
        accepted = admin.post(member_path + "/bind", json=body)
        assert accepted.status_code == 200, accepted.get_json()
        assert admin.get(member_path).get_json()["entity_id"] == target
    finally:
        maintenance.close()
        cleanup = psycopg2.connect(integration_stack.admin_url)
        cleanup.autocommit = True
        try:
            with cleanup.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
                )
        finally:
            cleanup.close()
