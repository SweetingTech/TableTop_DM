from __future__ import annotations

import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Event

import psycopg2.errors
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import discover, migrate
from kernel.checkpoint_holds import PostgresCheckpointHolds
from kernel.database import transaction
from tests.integration.test_action_rules import player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_campaign_checkpoint_holds import hold_path, player_speech

pytestmark = pytest.mark.integration


def test_checkpoint_hold_survives_restart_and_waits_for_exact_outbox(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    app, (admin, player, card, path, run, resident, base) = prepare(stack, monkeypatch, tmp_path)
    entry = hold_path(base)
    request = {"request_id": str(uuid.uuid4())}
    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"
    with monkeypatch.context() as patch:
        patch.setattr(app.extensions["simulation"], "subjective_projector", None)
        spoken = player_speech(player, base, card, "durable-checkpoint-prefix")
    assert spoken.status_code == 200, spoken.get_json()
    source = spoken.get_json()
    source_id = source["event"]["event_id"]
    projector = WorldEventProjector(stack.database_url, worker_id="checkpoint-outbox")
    (pending,) = projector._claim(1, topic=topic)
    assert str(pending.event.event_id) == source_id

    held = admin.post(entry, json=request)
    assert held.status_code == 200, held.get_json()
    started = held.get_json()
    assert started["status"] == "DRAINING" and started["pending_events"] == 1
    assert started["hold"]["through_event_id"] == source_id
    assert started["hold"]["state_hash"] == source["state_hash"]
    assert admin.post(entry, json={"request_id": str(uuid.uuid4())}).status_code == 409
    assert player.get(entry).status_code == 403

    _, restarted_admin = fresh_client(tmp_path)
    _, restarted_player = player_after_restart(tmp_path, player)
    assert restarted_admin.get(entry).get_json() == started
    retry = player_speech(restarted_player, base, card, "durable-checkpoint-prefix")
    assert retry.status_code == 200 and retry.get_json()["event"] == source["event"]
    rejected = player_speech(restarted_player, base, card, "after-durable-hold")
    assert rejected.status_code == 409 and rejected.get_json()["error"] == "branch_checkpoint_held"
    assert (
        restarted_player.post(
            path + "/control",
            json={"run_id": run, "expected_epoch": 0, "mode": "HUMAN", "idempotency_key": "new"},
        ).status_code
        == 409
    )

    projector._process_claim(pending)
    ready = restarted_admin.get(entry).get_json()
    assert ready == {**started, "status": "READY", "pending_events": 0}
    resident_path = path.removesuffix(card["entity_id"]) + resident
    scene = restarted_admin.get(resident_path + "/scene").get_json()
    assert "The ferry is ready." in str(scene["recent_observations"])

    release = f"{entry}/{request['request_id']}/release"
    assert restarted_player.post(release).status_code == 403
    released = restarted_admin.post(release).get_json()
    assert released["status"] == "RELEASED"
    assert restarted_admin.post(release).get_json() == released
    assert restarted_admin.post(entry, json=request).get_json() == released
    assert player_speech(restarted_player, base, card, "after-durable-hold").status_code == 200


def test_checkpoint_hold_grants_preserve_boundary_and_world_scope(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, _card, _path, _run, _resident, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    entry = hold_path(base)
    created = admin.post(entry, json={"request_id": str(uuid.uuid4())})
    assert created.status_code == 200, created.get_json()
    second_world = admin.post("/api/v2/worlds", json={"name": "Other checkpoint world"})
    other = second_world.get_json()["world_id"]
    mixed = hold_path({**base, "world_id": other})
    assert admin.post(mixed, json={"request_id": str(uuid.uuid4())}).status_code == 404
    actor = app.extensions["demo_ids"]["actor_id"]
    player_actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    dsn = integration_stack.database_url
    with transaction(dsn=dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM sim.campaign_checkpoint_holds")
        assert cursor.fetchone() == (0,)
    with transaction(actor_id=player_actor, dsn=dsn) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE sim.campaign_checkpoint_holds SET released_at=clock_timestamp()")
        assert cursor.rowcount == 0
    with (
        pytest.raises(psycopg2.errors.InsufficientPrivilege),
        transaction(actor_id=actor, dsn=dsn) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("UPDATE sim.campaign_checkpoint_holds SET projection_version=0")
    with (
        pytest.raises(psycopg2.errors.InsufficientPrivilege),
        transaction(actor_id=actor, dsn=dsn) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM sim.campaign_checkpoint_holds")


def test_checkpoint_boundary_serializes_with_a_concurrent_typed_action(
    integration_stack, monkeypatch, tmp_path
):
    _, (admin, player, card, _path, _run, _resident, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    entry = hold_path(base)
    request = {"request_id": str(uuid.uuid4())}
    locked, proceed = Event(), Event()
    original = PostgresCheckpointHolds._require_branch

    def synchronize(cursor, world, branch, *, lock=False):
        original(cursor, world, branch, lock=lock)
        if lock:
            locked.set()
            assert proceed.wait(15), "test did not let the hold commit"

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(PostgresCheckpointHolds, "_require_branch", staticmethod(synchronize))
        hold = pool.submit(admin.post, entry, json=request)
        try:
            assert locked.wait(15), "hold did not acquire the shared branch lock"
            action = pool.submit(player_speech, player, base, card, "concurrent-with-hold")
            with pytest.raises(TimeoutError):
                action.result(timeout=0.2)
        finally:
            proceed.set()
        assert hold.result(timeout=15).status_code == 200
        rejected = action.result(timeout=15)
    assert rejected.status_code == 409
    assert rejected.get_json()["error"] == "branch_checkpoint_held"
    release = f"{entry}/{request['request_id']}/release"
    assert admin.post(release).get_json()["status"] == "RELEASED"
    accepted = player_speech(player, base, card, "concurrent-with-hold")
    assert accepted.status_code == 200, accepted.get_json()


def test_021_upgrade_preserves_committed_cut_and_can_be_repeated(
    integration_stack, monkeypatch, tmp_path, pre_checkpoint_commands
):
    stack = integration_stack
    name = "ttdm_checkpoint_upgrade_" + uuid.uuid4().hex
    owner_url = make_dsn(stack.admin_url, dbname=name)
    runtime_url = make_dsn(stack.database_url, dbname=name)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in discover(migrations)[:20]:
        shutil.copy2(migrations / migration.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner_url, prior) == 20
            with pre_checkpoint_commands(owner_url):
                _, game = prepare(replace(stack, database_url=owner_url), monkeypatch, tmp_path)
                _, player, card, _, _, _, base = game
                spoken = player_speech(player, base, card, "before-checkpoint-migration")
                assert spoken.status_code == 200, spoken.get_json()
            before = spoken.get_json()

            sql_021 = (migrations / "021_campaign_checkpoint_holds.sql").read_text(encoding="utf-8")
            with closing(psycopg2.connect(owner_url)) as connection, connection.cursor() as cursor:
                cursor.execute(sql_021)
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_checkpoint_holds')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(migrations / "021_campaign_checkpoint_holds.sql", prior)
            assert migrate(owner_url, prior) == 1
            assert migrate(owner_url, prior) == 0
            monkeypatch.setenv("DATABASE_URL", runtime_url)
            _, restarted_admin = fresh_client(tmp_path)
            entry = hold_path(base)
            assert restarted_admin.get(entry).get_json() == {"hold": None}
            hold = restarted_admin.post(entry, json={"request_id": str(uuid.uuid4())})
            assert hold.status_code == 200, hold.get_json()
            assert hold.get_json()["hold"]["state_hash"] == before["state_hash"]
            assert hold.get_json()["hold"]["through_event_id"] == before["event"]["event_id"]
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
