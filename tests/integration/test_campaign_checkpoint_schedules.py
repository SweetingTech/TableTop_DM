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
from kernel.database import transaction
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_campaign_checkpoint_holds import hold_path, player_speech
from tests.unit.kernel.test_world_time import NOW

pytestmark = pytest.mark.integration


def rule_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/checkpoint-schedule"


def saved_receipts(stack, base):
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT manifest FROM sim.campaign_checkpoints WHERE (world_id,branch_id)=(%s,%s) "
            "ORDER BY created_at,checkpoint_id",
            (base["world_id"], base["branch_id"]),
        )
        return [row[0] for row in cursor.fetchall()]


def test_event_schedule_pins_exact_hold_and_finishes_after_worker_restart(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, _path, _run, _resident, base) = prepare(stack, monkeypatch, tmp_path)
    entry = rule_path(base)
    rule_id = str(uuid.uuid4())
    rule = {"rule_id": rule_id, "label": "Testimony", "event_types": ["tabletop.dialogue.speak"]}
    assert admin.get(entry).get_json() == {"rule": None}
    assert player.put(entry, json=rule).status_code == 403
    saved = admin.put(entry, json=rule)
    assert saved.status_code == 200, saved.get_json()
    assert admin.put(entry, json=rule).get_json() == saved.get_json()
    assert admin.put(entry, json={**rule, "rule_id": str(uuid.uuid4())}).status_code == 409
    player_actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with transaction(actor_id=player_actor, dsn=stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM sim.campaign_checkpoint_rules")
            assert cursor.fetchone() == (0,)
            cursor.execute(
                "SELECT has_function_privilege('sim.arm_campaign_checkpoint()', 'EXECUTE')"
            )
            assert cursor.fetchone() == (False,)

    with monkeypatch.context() as patch:
        patch.setattr(app.extensions["simulation"], "subjective_projector", None)
        action = player_speech(player, base, card, "scheduled-origin")
    assert action.status_code == 200, action.get_json()
    event_id = action.get_json()["event"]["event_id"]
    hold = admin.get(hold_path(base)).get_json()
    assert hold["status"] == "DRAINING"
    assert hold["hold"]["through_event_id"] == event_id
    assert player_speech(player, base, card, "blocked-by-schedule").status_code == 409

    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"
    projector = WorldEventProjector(stack.database_url, worker_id="checkpoint-schedule")
    (pending,) = projector._claim(1, topic=topic)
    assert str(pending.event.event_id) == event_id
    restarted, operator = fresh_client(tmp_path)
    assert restarted.extensions["world_runner"].run_once(NOW) == 0
    assert saved_receipts(stack, base) == []
    projector._process_claim(pending)
    assert restarted.extensions["world_runner"].run_once(NOW) == 0
    assert operator.get(hold_path(base)).get_json() == {"hold": None}
    (manifest,) = saved_receipts(stack, base)
    assert manifest["boundary"]["trigger_event_id"] == event_id
    assert manifest["boundary"]["trigger_schedule_id"] == rule_id
    assert manifest["boundary"]["state_hash"] == action.get_json()["state_hash"]
    assert operator.post(f"{entry}/{rule_id}/retire").status_code == 204
    assert (
        player_speech(player, base, card, "scheduled-origin").get_json()["event"]
        == action.get_json()["event"]
    )
    assert player_speech(player, base, card, "blocked-by-schedule").status_code == 200
    assert len(saved_receipts(stack, base)) == 1


def test_clock_schedule_captures_one_committed_cut_per_crossing(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, _player, _card, _path, _run, _resident, base) = prepare(
        stack, monkeypatch, tmp_path
    )
    entry = rule_path(base)
    rule_id = str(uuid.uuid4())
    configured = admin.put(
        entry,
        json={
            "rule_id": rule_id,
            "label": "Camp clock",
            "interval_seconds": 12,
        },
    )
    assert configured.status_code == 200, configured.get_json()
    assert configured.get_json()["anchor_seconds"] == 0

    advance_clock(admin, base, 6)
    assert admin.get(hold_path(base)).get_json() == {"hold": None}
    advance_clock(admin, base, 12)
    assert admin.get(hold_path(base)).get_json()["hold"]["simulated_seconds"] == 12
    app.extensions["world_runner"].run_once(NOW)
    advance_clock(admin, base, 36)
    assert admin.get(hold_path(base)).get_json()["hold"]["simulated_seconds"] == 36
    app.extensions["world_runner"].run_once(NOW)
    assert admin.get(hold_path(base)).get_json() == {"hold": None}
    checkpoints = saved_receipts(stack, base)
    assert [row["boundary"]["simulated_seconds"] for row in checkpoints] == [12, 36]
    assert {row["boundary"]["trigger_schedule_id"] for row in checkpoints} == {rule_id}


def test_023_upgrade_preserves_existing_archives_and_enables_schedules(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_schedule_upgrade_" + uuid.uuid4().hex
    owner_url = make_dsn(stack.admin_url, dbname=name)
    runtime_url = make_dsn(stack.database_url, dbname=name)
    pending = replace(stack, admin_url=owner_url, database_url=runtime_url)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in discover(migrations)[:22]:
        shutil.copy2(migrations / migration.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner_url, prior) == 22
            _, (admin, _player, _card, _path, _run, _resident, base) = prepare(
                pending, monkeypatch, tmp_path
            )
            entry = hold_path(base)
            request = str(uuid.uuid4())
            assert admin.post(entry, json={"request_id": request}).get_json()["status"] == "READY"
            capture = f"{entry}/{request}/capture"
            body = {"label": "Manual checkpoint before the schedule upgrade"}
            original = admin.post(capture, json=body)
            assert original.status_code == 200, original.get_json()
            admin.post(f"{entry}/{request}/release")

            latest = migrations / "023_campaign_checkpoint_schedules.sql"
            with closing(psycopg2.connect(owner_url)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_checkpoint_rules')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner_url, prior) == 1
            assert migrate(owner_url, prior) == 0
            _, restored = fresh_client(tmp_path)
            assert restored.post(capture, json=body).get_json() == original.get_json()
            assert restored.get(rule_path(base)).get_json() == {"rule": None}
            rule = restored.put(
                rule_path(base),
                json={
                    "rule_id": str(uuid.uuid4()),
                    "label": "After upgrade",
                    "interval_seconds": 6,
                },
            )
            assert rule.status_code == 200, rule.get_json()
            advance_clock(restored, base, 6)
            assert restored.get(entry).get_json()["hold"]["simulated_seconds"] == 6
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
