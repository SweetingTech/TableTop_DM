from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import psycopg2
import psycopg2.errors
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import discover, migrate
from kernel.campaign_checkpoints import CampaignCheckpointStore
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_schedules import rule_path, saved_receipts
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_campaign_checkpoint_holds import hold_path
from tests.unit.kernel.test_world_time import NOW

pytestmark = pytest.mark.integration


def retention_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/checkpoint-retention"


def manual_capture(admin, base):
    entry = hold_path(base)
    request_id = str(uuid.uuid4())
    assert admin.post(entry, json={"request_id": request_id}).get_json()["status"] == "READY"
    capture = f"{entry}/{request_id}/capture"
    result = admin.post(capture, json={"label": "Manual milestone"})
    assert result.status_code == 200, result.get_json()
    assert admin.post(f"{entry}/{request_id}/release").status_code == 200
    return result.get_json()["manifest"]["checkpoint_id"]


def scheduled_captures(stack, app, admin, base, cuts):
    configured = admin.put(
        rule_path(base),
        json={"rule_id": str(uuid.uuid4()), "label": "Camp clock", "interval_seconds": 6},
    )
    assert configured.status_code == 200, configured.get_json()
    worker = app.extensions["world_runner"]
    projector = WorldEventProjector(stack.database_url)
    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"
    for cut in cuts:
        advance_clock(admin, base, cut)
        worker.run_once(NOW)
        status = admin.get(hold_path(base)).get_json()
        deadline = monotonic() + 10
        while status.get("status") == "DRAINING" and monotonic() < deadline:
            projector.run_once(topic=topic)
            worker.run_once(NOW)
            status = admin.get(hold_path(base)).get_json()
            if status.get("status") == "DRAINING":
                sleep(0.05)
        assert status == {"hold": None}
    automatic = [
        manifest
        for manifest in saved_receipts(stack, base)
        if manifest["boundary"]["trigger_schedule_id"] is not None
    ]
    automatic.sort(key=lambda manifest: manifest["boundary"]["through_event_seq"])
    return [manifest["checkpoint_id"] for manifest in automatic]


def test_retention_preserves_pinned_manual_and_newest_archives_across_restart(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, _card, _path, _run, _resident, base) = prepare(
        stack, monkeypatch, tmp_path
    )
    entry = retention_path(base)
    archive_root = entry.rsplit("/", 1)[0] + "/campaign-checkpoints"
    manual = manual_capture(admin, base)
    oldest, pinned, latest = scheduled_captures(stack, app, admin, base, [6, 12, 18])
    policy = {"policy_id": str(uuid.uuid4()), "keep_automatic": 1}
    assert admin.get(entry).get_json() == {"policy": None}
    assert admin.post(f"{entry}/apply", json={"policy_id": policy["policy_id"]}).status_code == 409
    assert player.put(entry, json=policy).status_code == 403
    configured = admin.put(entry, json=policy)
    assert configured.status_code == 200, configured.get_json()
    assert admin.put(entry, json=policy).get_json() == configured.get_json()
    assert admin.put(entry, json={**policy, "policy_id": str(uuid.uuid4())}).status_code == 409
    pin_path = f"{archive_root}/{pinned}/pin"
    assert player.put(pin_path, json={"pinned": True}).status_code == 403
    assert admin.put(pin_path, json={"pinned": True}).get_json()["status"] == "PINNED"

    operator = uuid.UUID(admin.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with pytest.raises(psycopg2.errors.CheckViolation):
        with transaction(actor_id=operator, dsn=stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sim.campaign_checkpoint_retention_state "
                    "(world_id,branch_id,checkpoint_id,actor_id,status,policy_id) "
                    "VALUES (%s,%s,%s,%s,'RETIRED',%s)",
                    (
                        base["world_id"],
                        base["branch_id"],
                        latest,
                        str(operator),
                        policy["policy_id"],
                    ),
                )
    player_actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with transaction(actor_id=player_actor, dsn=stack.database_url) as connection:
        with connection.cursor() as cursor:
            for table in ("campaign_checkpoint_retention", "campaign_checkpoint_retention_state"):
                cursor.execute(sql.SQL("SELECT count(*) FROM sim.{}").format(sql.Identifier(table)))
                assert cursor.fetchone() == (0,)

    cleanup = CampaignCheckpointStore.remove_retired
    with monkeypatch.context() as patch:

        def interrupted_cleanup(_self, _manifest):
            raise OSError("cleanup interrupted")

        patch.setattr(CampaignCheckpointStore, "remove_retired", interrupted_cleanup)
        first = admin.post(f"{entry}/apply", json={"policy_id": policy["policy_id"]})
    assert first.get_json() == {"retired_checkpoint_ids": [oldest], "cleanup_pending": 1}
    _, restored = fresh_client(tmp_path)
    assert restored.get(entry).get_json() == configured.get_json()
    removed = []

    def tracked_cleanup(self, manifest):
        cleanup(self, manifest)
        removed.append(manifest.checkpoint_id)
        assert not self._path(manifest).exists()

    with monkeypatch.context() as patch:
        patch.setattr(CampaignCheckpointStore, "remove_retired", tracked_cleanup)
        retried = restored.post(f"{entry}/apply", json={"policy_id": policy["policy_id"]})
    assert retried.get_json() == {"retired_checkpoint_ids": [], "cleanup_pending": 0}
    assert removed == [uuid.UUID(oldest)]
    assert restored.get(f"{archive_root}/{oldest}").status_code == 409
    assert restored.put(f"{archive_root}/{oldest}/pin", json={"pinned": True}).status_code == 409
    assert tuple(
        restored.get(f"{archive_root}/{key}").status_code for key in (manual, pinned, latest)
    ) == (
        200,
        200,
        200,
    )
    assert len(saved_receipts(stack, base)) == 4
    assert restored.put(pin_path, json={"pinned": False}).get_json()["status"] == "AVAILABLE"
    assert restored.post(f"{entry}/apply", json={"policy_id": policy["policy_id"]}).get_json()[
        "retired_checkpoint_ids"
    ] == [pinned]


def test_retention_rolls_back_when_newest_artifact_is_corrupt(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, _player, _card, _path, _run, _resident, base) = prepare(
        stack, monkeypatch, tmp_path
    )
    oldest, latest = scheduled_captures(stack, app, admin, base, [6, 12])
    entry = retention_path(base)
    archive_root = entry.rsplit("/", 1)[0] + "/campaign-checkpoints"
    (artifact,) = tmp_path.rglob(f"{latest}.json.gz")
    artifact.write_bytes(b"unreadable checkpoint")
    policy = {"policy_id": str(uuid.uuid4()), "keep_automatic": 1}
    assert admin.put(entry, json=policy).status_code == 200
    result = admin.post(f"{entry}/apply", json={"policy_id": policy["policy_id"]})
    assert result.status_code == 409, result.get_json()
    assert admin.get(f"{archive_root}/{oldest}").status_code == 200


def test_024_upgrade_preserves_existing_archive_and_rolls_back_ddl(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_checkpoint_retention_" + uuid.uuid4().hex
    owner_url = make_dsn(stack.admin_url, dbname=name)
    runtime_url = make_dsn(stack.database_url, dbname=name)
    pending = replace(stack, admin_url=owner_url, database_url=runtime_url)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in discover(migrations)[:23]:
        shutil.copy2(migrations / migration.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner_url, prior) == 23
            _, (admin, _player, _card, _path, _run, _resident, base) = prepare(
                pending, monkeypatch, tmp_path
            )
            checkpoint = manual_capture(admin, base)
            latest = migrations / "024_campaign_checkpoint_retention.sql"
            with closing(psycopg2.connect(owner_url)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_checkpoint_retention')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner_url, prior) == 1
            assert migrate(owner_url, prior) == 0
            _, restored = fresh_client(tmp_path)
            entry = retention_path(base)
            archive_root = entry.rsplit("/", 1)[0] + "/campaign-checkpoints"
            assert restored.get(f"{archive_root}/{checkpoint}").status_code == 200
            assert restored.get(entry).get_json() == {"policy": None}
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
