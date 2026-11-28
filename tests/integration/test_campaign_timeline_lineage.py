from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import discover, migrate
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_campaign_checkpoint_holds import player_speech

pytestmark = pytest.mark.integration


def test_active_pointer_hydrates_world_and_excludes_trials(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    _, (admin, player, _card, _path, _run, _resident, base) = prepare(stack, monkeypatch, tmp_path)
    world = base["world_id"]
    branch = base["branch_id"]
    world_path = f"/api/v2/worlds/{world}"
    state = admin.get(world_path).get_json()
    assert state["canonical_branch_id"] == branch
    assert state["continuation_epoch"] == 0
    listed = next(row for row in admin.get("/api/v2/worlds").get_json() if row["world_id"] == world)
    assert listed["current_run_id"] == base["run_id"]
    checkpoint_id = manual_capture(admin, base)
    manifest = admin.get(
        f"{world_path}/branches/{branch}/campaign-checkpoints/{checkpoint_id}"
    ).get_json()["manifest"]
    assert manifest["boundary"]["continuation_epoch"] == state["continuation_epoch"]
    snapshot = admin.post(f"{world_path}/snapshots")
    assert snapshot.status_code == 201, snapshot.get_json()
    trial = admin.post(
        f"/api/v2/snapshots/{snapshot.get_json()['snapshot_id']}/branches", json={"seed": 117}
    )
    assert trial.status_code == 201, trial.get_json()
    trial_id = trial.get_json()["branch_id"]
    assert trial_id != branch

    player_actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with transaction(actor_id=player_actor, dsn=stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT world_id,branch_id,epoch FROM sim.campaign_continuations")
            assert cursor.fetchall() == [(world, branch, 0)]
            cursor.execute("SELECT count(*) FROM sim.campaign_timeline_lineage")
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT has_function_privilege('sim.bootstrap_campaign_continuation()', 'EXECUTE')"
            )
            assert cursor.fetchone() == (False,)
    operator = uuid.UUID(admin.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with transaction(actor_id=operator, dsn=stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT branch_id,epoch,parent_branch_id,source_checkpoint_id "
                "FROM sim.campaign_timeline_lineage WHERE world_id=%s",
                (world,),
            )
            assert cursor.fetchall() == [(branch, 0, None, None)]
            cursor.execute(
                "SELECT sim.can_mutate_branch(%s,%s),sim.can_mutate_branch(%s,%s)",
                (world, branch, world, trial_id),
            )
            assert cursor.fetchone() == (True, True)
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with transaction(actor_id=operator, dsn=stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE sim.campaign_continuations SET branch_id=%s WHERE world_id=%s",
                    (trial_id, world),
                )
    _, restored = fresh_client(tmp_path)
    reopened = restored.get(world_path).get_json()
    assert reopened["canonical_branch_id"] == branch
    assert reopened["continuation_epoch"] == 0
    listed = next(
        row for row in restored.get("/api/v2/worlds").get_json() if row["world_id"] == world
    )
    assert listed["current_run_id"] == base["run_id"]


def test_archived_canonical_branch_replays_receipt_but_cannot_commit(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    _, (_admin, player, card, _path, _run, _resident, base) = prepare(stack, monkeypatch, tmp_path)
    original = player_speech(player, base, card, "before-archive")
    assert original.status_code == 200, original.get_json()
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sim.branches SET status='ARCHIVED',completed_at=clock_timestamp() "
            "WHERE (world_id,id)=(%s,%s)",
            (base["world_id"], base["branch_id"]),
        )
    retry = player_speech(player, base, card, "before-archive")
    assert retry.status_code == 200, retry.get_json()
    assert retry.get_json()["event"] == original.get_json()["event"]
    blocked = player_speech(player, base, card, "new-after-archive")
    assert blocked.status_code == 409, blocked.get_json()


def test_025_upgrade_backfills_the_continue_pointer_and_rolls_back_ddl(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_timeline_upgrade_" + uuid.uuid4().hex
    owner_url = make_dsn(stack.admin_url, dbname=name)
    runtime_url = make_dsn(stack.database_url, dbname=name)
    pending = replace(stack, admin_url=owner_url, database_url=runtime_url)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in discover(migrations)[:24]:
        shutil.copy2(migrations / migration.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner_url, prior) == 24
            _, (admin, _player, _card, _path, _run, _resident, base) = prepare(
                pending, monkeypatch, tmp_path
            )
            world_path = f"/api/v2/worlds/{base['world_id']}"
            original = admin.get(world_path).get_json()
            latest = migrations / "025_campaign_timeline_lineage.sql"
            with closing(psycopg2.connect(owner_url)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_continuations')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner_url, prior) == 1
            assert migrate(owner_url, prior) == 0
            with transaction(dsn=owner_url) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT branch_id,epoch FROM sim.campaign_continuations WHERE world_id=%s",
                    (base["world_id"],),
                )
                assert cursor.fetchone() == (base["branch_id"], 0)
            _, restored = fresh_client(tmp_path)
            assert restored.get(world_path).get_json() == original
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
