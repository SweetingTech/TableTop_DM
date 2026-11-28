from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import discover, migrate
from kernel.campaign_checkpoints import (
    CampaignCheckpointStore,
    CheckpointSection,
    FrozenComponent,
    PinnedComponent,
)
from kernel.checkpoint_holds import PostgresCheckpointHolds
from kernel.database import transaction
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_campaign_checkpoint_holds import hold_path, player_speech
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.integration


def test_capture_uses_one_projected_cut_and_loads_private_state_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    app, (admin, player, card, _path, _run, resident, base) = prepare(stack, monkeypatch, tmp_path)
    seed_routine(app, admin, base, resident)
    archived_body = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": archived_body,
            "name": "Archive warden",
            "entity_type": "NPC",
            "public_state": {"x": 20, "y": 20, "hp": 17},
            "secret_state": {"identity": "WARDEN_PRIVATE_IDENTITY"},
        },
        "spawn-private-warden",
    )
    with monkeypatch.context() as patch:
        patch.setattr(app.extensions["simulation"], "subjective_projector", None)
        said = player_speech(player, base, card, "checkpoint-first-testimony")
    assert said.status_code == 200, said.get_json()
    original = said.get_json()
    request = str(uuid.uuid4())
    held = admin.post(hold_path(base), json={"request_id": request})
    assert held.get_json()["status"] == "DRAINING"
    capture = f"{hold_path(base)}/{request}/capture"
    label = {"label": "Before the ferry raid"}
    assert player.post(capture, json=label).status_code == 403
    assert admin.post(capture, json=label).status_code == 409

    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"
    assert WorldEventProjector(stack.database_url).run_once(topic=topic) == 1
    (pool,) = (tmp_path / "populations").glob("*.parquet")
    pool_bytes = pool.read_bytes()
    pool.write_bytes(b"bad population artifact")
    try:
        unavailable = admin.post(capture, json=label)
        assert unavailable.status_code == 409
        assert unavailable.get_json()["details"] == "a checkpoint source artifact is unavailable"
    finally:
        pool.write_bytes(pool_bytes)
    created = admin.post(capture, json=label)
    assert created.status_code == 200, created.get_json()
    receipt = created.get_json()
    manifest = receipt["manifest"]
    assert "WARDEN_PRIVATE_IDENTITY" not in str(receipt)
    assert "PRIVATE_GARDEN_HISTORY" not in str(receipt)
    assert manifest["boundary"]["state_hash"] == original["state_hash"]
    assert manifest["boundary"]["through_event_id"] == original["event"]["event_id"]
    assert admin.post(capture, json=label).get_json() == receipt
    assert admin.post(capture, json={"label": "Different title"}).status_code == 409

    checkpoint_id = uuid.UUID(manifest["checkpoint_id"])
    world, branch = uuid.UUID(base["world_id"]), uuid.UUID(base["branch_id"])
    _, restarted_admin = fresh_client(tmp_path)
    path = f"/api/v2/worlds/{world}/branches/{branch}/campaign-checkpoints/{checkpoint_id}"
    assert restarted_admin.get(path).get_json() == receipt
    assert player.get(path).status_code == 403
    archives = PostgresCampaignCheckpoints(
        stack.database_url,
        tmp_path / "campaign-checkpoints",
        PostgresCheckpointHolds(stack.database_url),
    )
    actor = app.extensions["demo_ids"]["actor_id"]
    _, bundle = archives.load(world, branch, checkpoint_id, actor)
    assert bundle.entities[archived_body].secret_state == {"identity": "WARDEN_PRIVATE_IDENTITY"}
    minds = bundle.sections[CheckpointSection.MINDS]
    assert isinstance(minds, FrozenComponent)
    assert any(
        row["observer_entity_id"] == resident
        and row["source_event_id"] == original["event"]["event_id"]
        and row["perceived_payload"]["text"] == "The ferry is ready."
        for row in minds.data["cognition.observations"]
    )
    pinned = bundle.sections[CheckpointSection.VERSIONED_ARTIFACTS]
    assert isinstance(pinned, PinnedComponent)
    assert {item.kind for item in pinned.references} >= {
        "artifact",
        "authored-card",
        "persona-blueprint",
        "persona-schema",
        "compiled-persona",
    }
    population = bundle.sections[CheckpointSection.POPULATION]
    assert isinstance(population, FrozenComponent)
    assert len(population.data["population.definitions"]) == 1
    assert len(population.data["population.pools"]) == 1
    assert len(population.data["population.materialized_people"]) == 1
    assert (
        restarted_admin.post(f"{hold_path(base)}/{request}/release").get_json()["status"]
        == "RELEASED"
    )
    after = player_speech(player, base, card, "newer-than-checkpoint")
    assert after.status_code == 200, after.get_json()
    assert restarted_admin.post(capture, json=label).get_json() == receipt
    assert archives.load(world, branch, checkpoint_id, actor)[1] == bundle
    artifact = tmp_path / "campaign-checkpoints" / base["world_id"] / f"{checkpoint_id}.json.gz"
    artifact.write_bytes(b"corrupt checkpoint")
    corrupted = restarted_admin.get(path)
    assert corrupted.status_code == 409
    assert corrupted.get_json()["details"] == "checkpoint archive could not be verified"


def test_failed_receipt_insert_leaves_no_visible_checkpoint(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    _, (admin, _player, _card, _path, _run, _resident, base) = prepare(stack, monkeypatch, tmp_path)
    request = str(uuid.uuid4())
    entry = hold_path(base)
    assert admin.post(entry, json={"request_id": request}).get_json()["status"] == "READY"
    capture = f"{entry}/{request}/capture"
    original = CampaignCheckpointStore.create
    ids = []

    def wrong_cut(self, checkpoint):
        manifest = original(self, checkpoint)
        ids.append(manifest.checkpoint_id)
        return manifest.model_copy(
            update={
                "boundary": manifest.boundary.model_copy(
                    update={"projection_version": manifest.boundary.projection_version + 1}
                )
            }
        )

    with monkeypatch.context() as patch:
        patch.setattr(CampaignCheckpointStore, "create", wrong_cut)
        rejected = admin.post(capture, json={"label": "Ferry approach"})
        assert rejected.status_code == 409
        assert rejected.get_json()["details"] == "checkpoint scope changed before publication"
    assert len(ids) == 1
    world, branch = base["world_id"], base["branch_id"]
    path = f"/api/v2/worlds/{world}/branches/{branch}/campaign-checkpoints/{ids[0]}"
    assert admin.get(path).status_code == 404
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM sim.campaign_checkpoints WHERE checkpoint_id=%s", (str(ids[0]),)
        )
        assert cursor.fetchone() == (0,)
    retried = admin.post(capture, json={"label": "Ferry approach"})
    assert retried.status_code == 200, retried.get_json()
    assert retried.get_json()["manifest"]["checkpoint_id"] == str(ids[0])


def test_022_upgrade_captures_a_preexisting_hold(integration_stack, monkeypatch, tmp_path):
    stack = integration_stack
    name = "ttdm_archive_upgrade_" + uuid.uuid4().hex
    owner_url = make_dsn(stack.admin_url, dbname=name)
    runtime_url = make_dsn(stack.database_url, dbname=name)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in discover(migrations)[:21]:
        shutil.copy2(migrations / migration.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner_url, prior) == 21
            _, (admin, _player, _card, _path, _run, _resident, base) = prepare(
                replace(stack, database_url=runtime_url), monkeypatch, tmp_path
            )
            entry = hold_path(base)
            request = str(uuid.uuid4())
            original = admin.post(entry, json={"request_id": request}).get_json()
            assert original["status"] == "READY"

            latest = migrations / "022_campaign_checkpoints.sql"
            with closing(psycopg2.connect(owner_url)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_checkpoints')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner_url, prior) == 1
            assert migrate(owner_url, prior) == 0
            _, restored = fresh_client(tmp_path)
            assert restored.get(entry).get_json() == original
            captured = restored.post(
                f"{entry}/{request}/capture", json={"label": "Before the raid"}
            )
            assert captured.status_code == 200, captured.get_json()
            assert (
                captured.get_json()["manifest"]["boundary"]["state_hash"]
                == original["hold"]["state_hash"]
            )
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
