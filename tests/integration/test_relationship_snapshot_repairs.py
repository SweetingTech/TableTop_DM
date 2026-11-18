from __future__ import annotations

import os
import secrets
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import discover, migrate
from kernel.api.app import create_app
from kernel.application import stable_id
from kernel.errors import BranchIsolationError
from kernel.postgres_control_plane import PostgresControlPlane
from kernel.snapshots import SnapshotStore
from tests.integration.test_world_time import prepare
from tests.unit.cognition.test_relationship_api import (
    check_grounded_relationships,
    physical_relationship_game,
)
from tests.unit.kernel.test_speech_combat_behavior import setup_scene
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.integration


def fresh_client(root):
    app = create_app(artifact_root=root)
    client = app.test_client()
    client.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    return app, client


def snapshot(admin, world, branch=None):
    response = admin.post(
        f"/api/v2/worlds/{world}/snapshots", json={"branch_id": branch} if branch else {}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def trial(admin, manifest, seed):
    response = admin.post(
        f"/api/v2/snapshots/{manifest['snapshot_id']}/branches", json={"seed": seed}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_physical_relationships_preserve_raw_acl_and_retry_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    scope = {**game[-1], "actor_id": app.extensions["demo_ids"]["actor_id"]}
    physical = physical_relationship_game(app, game[0], scope)
    endpoint, headers, payload, receipt = check_grounded_relationships(physical)
    _, restored = fresh_client(tmp_path)
    assert restored.post(endpoint, headers=headers, json=payload).get_json() == receipt
    for client, key, expected in [
        (restored, "other-process", 3),
        (physical[0], "first-process-again", 4),
    ]:
        response = client.post(
            endpoint,
            headers=headers,
            json={**payload, "source_event_id": physical[-1](key)},
        )
        assert response.status_code == 201, response.get_json()
        assert response.get_json()["after"]["familiarity"] == expected
    assert restored.post(endpoint, headers=headers, json=payload).get_json() == receipt
    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT set_config('app.actor_id',%s,true)", (physical[2],))
        cursor.execute(
            "SELECT count(*) FROM sim.events WHERE event_id=%s", (payload["source_event_id"],)
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT familiarity FROM cognition.relationships "
            "WHERE source_entity_id=%s AND target_entity_id=%s",
            (physical[3], physical[4]),
        )
        assert cursor.fetchone()[0] == 4


def test_nested_trial_freezes_metadata_and_exact_snapshot_lineage(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, base = game[0], game[-1]
    world = base["world_id"]
    parent = trial(admin, snapshot(admin, world), 201)
    child = str(uuid.uuid4())
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "branch_id": parent["branch_id"],
            "run_id": parent["run"]["run_id"],
            "command_type": "tabletop.entity.spawn",
            "idempotency_key": "trial-child",
            "parameters": {
                "entity_id": child,
                "name": "Frozen child",
                "entity_type": "NPC",
                "secret_state": {"identity": "PAST_IDENTITY"},
                "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
                "public_state": {"x": 12, "y": 12, "hp": 17},
            },
        },
    )
    assert response.status_code == 200, response.get_json()
    frozen = snapshot(admin, world, parent["branch_id"])
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE sim.entities SET secret_state=%s::jsonb WHERE branch_id=%s AND id=%s",
            ('{"identity":"FUTURE_IDENTITY"}', parent["branch_id"], child),
        )
    later = snapshot(admin, world, parent["branch_id"])
    assert (
        frozen["state_hash"] == later["state_hash"]
        and frozen["snapshot_id"] != later["snapshot_id"]
    )
    _, restored = fresh_client(tmp_path)
    before, after = trial(restored, frozen, 202), trial(restored, later, 203)
    again, reader = fresh_client(tmp_path)
    listed = reader.get("/api/v2/branches", query_string={"world_id": world})
    assert listed.status_code == 200
    origins = {row["branch_id"]: row["base_snapshot_id"] for row in listed.get_json()}
    for branch, expected, manifest in [
        (before, "PAST_IDENTITY", frozen),
        (after, "FUTURE_IDENTITY", later),
    ]:
        assert origins[branch["branch_id"]] == manifest["snapshot_id"]
        record = again.extensions["simulation"].entities[
            (uuid.UUID(branch["branch_id"]), uuid.UUID(child))
        ]
        assert record.secret_state == {"identity": expected} and record.public_state["hp"] == 17
        assert record.controller_actor_id == app.extensions["demo_ids"]["actor_id"]
        assert again.extensions["simulation"].branch_snapshot_ids[
            uuid.UUID(branch["branch_id"])
        ] == uuid.UUID(manifest["snapshot_id"])
        replay = reader.get(f"/api/v2/branches/{branch['branch_id']}/replay")
        assert replay.status_code == 200 and replay.get_json()["verified"]
    assert (
        reader.post(
            f"/api/v2/snapshots/{frozen['snapshot_id']}/branches", json={"seed": 202}
        ).get_json()
        == before
    )
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.entities WHERE world_id=%s AND branch_id=%s AND id=%s",
            (world, base["branch_id"], child),
        )
        assert cursor.fetchone()[0] == 0


def test_capture_uses_locked_state_and_rolls_back_manifest_publication(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, base, sim, body = game[0], game[-1], app.extensions["simulation"], game[-2]
    sim.states.get(uuid.UUID(base["branch_id"])).projections["tabletop.entities"][body]["hp"] = 999
    sim.entities[(uuid.UUID(base["branch_id"]), uuid.UUID(body))].secret_state["cache"] = (
        "STALE_CACHE"
    )
    original = PostgresControlPlane.persist_snapshot

    def fail(self, manifest, version, **kwargs):
        original(self, manifest, version, **kwargs)
        if kwargs.get("cursor") is not None:
            raise RuntimeError("test snapshot rollback after insert")

    before = len(sim.snapshots)
    with monkeypatch.context() as patch:
        patch.setattr(PostgresControlPlane, "persist_snapshot", fail)
        assert (
            admin.post(f"/api/v2/worlds/{base['world_id']}/snapshots", json={}).status_code == 500
        )
    assert len(sim.snapshots) == before
    manifest = snapshot(admin, base["world_id"])
    payload = SnapshotStore.load(sim.snapshots[uuid.UUID(manifest["snapshot_id"])])
    assert payload["projections"]["tabletop.entities"][body]["hp"] != 999
    assert "cache" not in payload["entities"][body]["secret_state"]


def test_failed_trial_insert_is_atomic_and_retry_is_stable(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, world = game[0], game[-1]["world_id"]
    manifest, seed = snapshot(admin, world), 99161
    branch = stable_id(f"trial:{manifest['snapshot_id']}:{seed}")
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "CREATE FUNCTION sim.test_reject_trial_run() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.seed=99161 THEN RAISE EXCEPTION 'test trial run rollback'; "
            "END IF; RETURN NEW; END $$"
        )
        cursor.execute(
            "CREATE TRIGGER test_reject_trial_run BEFORE INSERT ON sim.runs "
            "FOR EACH ROW EXECUTE FUNCTION sim.test_reject_trial_run()"
        )
    try:
        response = admin.post(
            f"/api/v2/snapshots/{manifest['snapshot_id']}/branches", json={"seed": seed}
        )
        assert response.status_code == 500
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            for table, column in [
                ("branches", "id"),
                ("branch_projections", "branch_id"),
                ("entities", "branch_id"),
                ("runs", "branch_id"),
            ]:
                cursor.execute(
                    f"SELECT count(*) FROM sim.{table} WHERE {column}=%s", (str(branch),)
                )
                assert cursor.fetchone()[0] == 0
        with pytest.raises(BranchIsolationError):
            app.extensions["simulation"].states.get(branch)
    finally:
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("DROP TRIGGER test_reject_trial_run ON sim.runs")
            cursor.execute("DROP FUNCTION sim.test_reject_trial_run()")
    accepted = trial(admin, manifest, seed)
    assert trial(admin, manifest, seed) == accepted


def test_011_upgrade_preserves_legacy_snapshot_and_allows_metadata_identity(
    integration_stack, monkeypatch, tmp_path
):
    name = "ttdm_snapshot_upgrade_" + uuid.uuid4().hex
    url = make_dsn(integration_stack.admin_url, dbname=name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for migration in sorted(migrations.glob("*.sql"))[:11]:
            shutil.copy2(migration, prior / migration.name)
        assert migrate(url, prior) == 11
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
        app, client = fresh_client(tmp_path)
        world = client.post("/api/v2/worlds", json={"name": "Snapshot upgrade"}).get_json()
        game = setup_scene(app, scope=world)
        admin, base, sim = game[0], game[-1], app.extensions["simulation"]
        state = sim.states.get(uuid.UUID(base["branch_id"]))
        legacy = sim.snapshot_store.create(
            state.world_id,
            state.branch_id,
            len(sim.command_history[state.branch_id]),
            state.projections,
        )
        control = PostgresControlPlane(url)
        control.actor_id = app.extensions["demo_ids"]["actor_id"]
        control.persist_snapshot(legacy, state.version)
        assert migrate(url, migrations) == len(discover(migrations)) - 11
        assert migrate(url, migrations) == 0
        readiness = admin.get("/readyz")
        assert readiness.status_code == 200, readiness.get_json()
        expected_migration = discover(migrations)[-1].version
        assert readiness.get_json()["checks"]["postgres"]["migration"] == expected_migration
        frozen = snapshot(admin, base["world_id"])
        assert frozen["state_hash"] == legacy.state_hash
        assert frozen["snapshot_id"] != str(legacy.snapshot_id)
        assert SnapshotStore.load(legacy)["contract_version"] == "2.0.0"
        assert trial(admin, frozen, 801)["branch_kind"] == "TRIAL"
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id,contract_version FROM sim.snapshots WHERE world_id=%s "
                "AND id IN (%s,%s) ORDER BY contract_version",
                (base["world_id"], str(legacy.snapshot_id), frozen["snapshot_id"]),
            )
            assert cursor.fetchall() == [
                (str(legacy.snapshot_id), "2.0.0"),
                (frozen["snapshot_id"], "2.1.0"),
            ]
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


def test_snapshot_fence_serializes_a_real_command(integration_stack, monkeypatch, tmp_path):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, base = game[0], game[-1]
    _, concurrent = fresh_client(tmp_path)
    entered, release = Event(), Event()
    original = SnapshotStore.create

    def hold_capture(self, *args, **kwargs):
        entered.set()
        assert release.wait(15), "test capture release timed out"
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as pool:
        patch.setattr(SnapshotStore, "create", hold_capture)
        frozen = pool.submit(snapshot, admin, base["world_id"])
        try:
            assert entered.wait(15), "test capture did not enter fenced section"
            command = pool.submit(
                api_command,
                concurrent,
                base,
                "tabletop.clock.advance",
                {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 5},
                "capture-race",
            )
            with pytest.raises(TimeoutError):
                command.result(timeout=0.2)
        finally:
            release.set()
        manifest = frozen.result(timeout=15)
        command.result(timeout=15)
    payload = SnapshotStore.load(
        app.extensions["simulation"].snapshots[uuid.UUID(manifest["snapshot_id"])]
    )
    assert payload["projections"]["tabletop.clock"]["singleton"]["seconds"] == 0
    _, current = fresh_client(tmp_path)
    replay = current.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert (
        replay["verified"] and replay["projections"]["tabletop.clock"]["singleton"]["seconds"] == 5
    )


@pytest.mark.parametrize("operation", ["capture_snapshot", "persist_trial"])
def test_revoked_branch_authority_cannot_use_a_stale_api(
    integration_stack, monkeypatch, tmp_path, operation
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, base = game[0], game[-1]
    manifest = snapshot(admin, base["world_id"])
    actor = str(app.extensions["demo_ids"]["actor_id"])
    original = getattr(PostgresControlPlane, operation)

    def revoke(self, *args, **kwargs):
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "DELETE FROM sim.actor_capabilities WHERE world_id=%s AND actor_id=%s "
                "AND capability='run.branch'",
                (base["world_id"], actor),
            )
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresControlPlane, operation, revoke)
        if operation == "capture_snapshot":
            response = admin.post(f"/api/v2/worlds/{base['world_id']}/snapshots", json={})
        else:
            response = admin.post(
                f"/api/v2/snapshots/{manifest['snapshot_id']}/branches", json={"seed": 911}
            )
        assert response.status_code == 403, response.get_json()
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.branches WHERE world_id=%s AND branch_kind='TRIAL'",
            (base["world_id"],),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM sim.actor_capabilities WHERE world_id=%s AND actor_id=%s "
            "AND capability='run.branch'",
            (base["world_id"], actor),
        )
        assert cursor.fetchone()[0] == 0
