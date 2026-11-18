from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import migrate
from kernel.api.app import create_app
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.cognition.test_narration import exercise_narration

pytestmark = pytest.mark.integration


def test_scoped_narration_persists_across_restart_and_enforces_lineage(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, _, run, speaker, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    route, entries = exercise_narration(app, admin, player, card, run, speaker, base)
    restarted = create_app(artifact_root=tmp_path).test_client()
    restarted.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    key = entries[-1]["narration_id"]
    saved = restarted.get(route + "/" + key)
    assert saved.status_code == 200 and saved.get_json() == entries[-1]

    with psycopg2.connect(integration_stack.admin_url) as owner, owner.cursor() as cursor:
        cursor.execute(
            "SELECT requester_actor_id FROM cognition.narration_entries WHERE narration_id=%s",
            (key,),
        )
        player_actor = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM cognition.narration_entries WHERE run_id=%s", (run,))
        assert cursor.fetchone() == (6,)
        with pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState, match="append-only"):
            cursor.execute("DELETE FROM cognition.narration_entries WHERE narration_id=%s", (key,))
        owner.rollback()
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid="
            "'cognition.narration_entries'::regclass AND contype='f'"
        )
        assert len(cursor.fetchall()) == 4
        for column, value in (
            ("run_id", str(uuid.uuid4())),
            ("source_observation_id", entries[0]["source_observation_id"]),
        ):
            fields = [
                "requester_actor_id",
                "world_id",
                "branch_id",
                "run_id",
                "audience",
                "observer_entity_id",
                "source_event_id",
                "source_observation_id",
                "occurred_at",
                "version",
                "text",
            ]
            target = sql.SQL(", ").join(map(sql.Identifier, fields))
            source = sql.SQL(", ").join(
                sql.Placeholder() if field == column else sql.Identifier(field) for field in fields
            )
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO cognition.narration_entries (narration_id, {}) "
                        "SELECT %s, {} FROM cognition.narration_entries WHERE narration_id=%s"
                    ).format(target, source),
                    (str(uuid.uuid4()), value, key),
                )
            owner.rollback()

    with psycopg2.connect(integration_stack.database_url) as runtime, runtime.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM cognition.narration_entries WHERE run_id=%s", (run,))
        assert cursor.fetchone() == (0,)
        cursor.execute("SELECT set_config('app.actor_id', %s, true)", (player_actor,))
        cursor.execute("SELECT count(*) FROM cognition.narration_entries WHERE run_id=%s", (run,))
        assert cursor.fetchone() == (3,)
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cursor.execute(
                "UPDATE cognition.narration_entries SET text='changed' WHERE narration_id=%s",
                (key,),
            )
        runtime.rollback()

    with psycopg2.connect(integration_stack.admin_url) as owner, owner.cursor() as cursor:
        cursor.execute(
            "DELETE FROM sim.actor_capabilities WHERE actor_id=%s AND world_id=%s "
            "AND capability='world.read'",
            (player_actor, base["world_id"]),
        )
    assert restarted.get(route + "/" + key).status_code == 404


def test_migration_015_upgrade_can_roll_back_and_reapply(integration_stack, tmp_path):
    name = "ttdm_narration_upgrade_" + uuid.uuid4().hex
    admin = psycopg2.connect(integration_stack.admin_url)
    admin.autocommit = True
    dsn = make_dsn(integration_stack.admin_url, dbname=name)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in sorted(migrations.glob("*.sql"))[:14]:
        shutil.copy2(migration, prior / migration.name)
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        assert migrate(dsn, prior) == 14
        latest = migrations / "015_scoped_narration.sql"
        connection = psycopg2.connect(dsn)
        try:
            with connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('cognition.narration_entries')")
                assert cursor.fetchone() == (None,)
        finally:
            connection.close()
        shutil.copy2(latest, prior)
        assert migrate(dsn, prior) == 1
        assert migrate(dsn, prior) == 0
    finally:
        assert name.startswith("ttdm_narration_upgrade_") and len(name) == 55
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()
