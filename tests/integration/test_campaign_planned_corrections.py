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

from infra.migrate import discover, migrate
from kernel import revision_activation
from kernel.campaign_activation import ACTIVATE_CAMPAIGN_REVISION
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_campaign_corrections import state_at
from tests.integration.test_campaign_revision_plans import request_for, revision_path
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_campaign_checkpoint_holds import hold_path

pytestmark = pytest.mark.integration


def assert_revision_not_published(stack, old, new):
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM sim.branches WHERE world_id=%s "
            "AND branch_kind='CANONICAL' AND status='ACTIVE'",
            (old["world_id"],),
        )
        assert cursor.fetchall() == [(old["branch_id"],)]
        cursor.execute("SELECT 1 FROM sim.branches WHERE id=%s", (new,))
        assert cursor.fetchone() is None
        cursor.execute("SELECT 1 FROM sim.command_log WHERE branch_id=%s", (new,))
        assert cursor.fetchone() is None


def test_prepared_correction_and_pointer_commit_atomically_after_restart(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, _, _, _, target, initial) = prepare(stack, monkeypatch, tmp_path)
    original = state_at(app, initial)
    old_body = original.projections["tabletop.entities"][target]
    root = revision_path(initial)
    body = {
        **request_for(manual_capture(admin, initial)),
        "reason": "PRIVATE_PLANNED_CORRECTION_REASON",
        "corrections": [
            {"fact": "HIT_POINTS", "entity_id": target, "hit_points": 15},
            {"fact": "POSITION", "entity_id": target, "x": 4, "y": 2},
        ],
    }
    assert player.post(root, json=body).status_code == 403
    bad_batch = {**body, "corrections": [*body["corrections"], body["corrections"][0]]}
    invalid = admin.post(root, json=bad_batch)
    assert invalid.status_code == 400, invalid.get_json()
    assert invalid.get_json()["details"] == "invalid campaign revision parameters"
    assert body["reason"] not in invalid.get_data(as_text=True)
    assert state_at(app, initial).state_hash == original.state_hash
    prepared = admin.post(root, json=body)
    assert prepared.status_code == 200, prepared.get_json()
    plan = prepared.get_json()
    planned = plan["provenance"]["planned_correction"]
    assert planned["request"]["expected_epoch"] == 1
    assert planned["request"]["expected_state_hash"] == plan["candidate_state_hash"]
    assert planned["request"]["corrections"] == body["corrections"]
    assert admin.post(root, json=body).get_json() == plan
    assert (
        admin.post(root, json={**body, "corrections": body["corrections"][:1]}).status_code == 409
    )
    assert_revision_not_published(stack, initial, plan["successor_branch_id"])

    activate = f"{root}/{body['request_id']}/activate"
    commit = revision_activation.PostgresRevisionActivation._commit_correction

    def interrupted(self, *args):
        commit(self, *args)
        raise CheckpointHoldConflict("interrupted after staging the correction")

    with monkeypatch.context() as patch:
        patch.setattr(
            revision_activation.PostgresRevisionActivation, "_commit_correction", interrupted
        )
        failed = admin.post(activate)
    assert failed.status_code == 409, failed.get_json()
    assert failed.get_json()["details"] == "interrupted after staging the correction"
    assert_revision_not_published(stack, initial, plan["successor_branch_id"])
    assert admin.get(hold_path(initial)).get_json()["status"] == "READY"

    # The database must reject publication even if the API omits the planned write.
    with monkeypatch.context() as patch:
        patch.setattr(
            revision_activation.PostgresRevisionActivation, "_commit_correction", lambda *args: None
        )
        denied = admin.post(activate)
    assert denied.status_code == 409, denied.get_json()
    assert denied.get_json()["details"] == "campaign revision failed durable validation"
    assert_revision_not_published(stack, initial, plan["successor_branch_id"])

    restarted, operator = fresh_client(tmp_path)
    result = operator.post(activate)
    assert result.status_code == 200, result.get_json()
    activation = result.get_json()
    receipt = activation["receipt"]
    correction = receipt["correction"]
    assert receipt["state_hash"] == plan["candidate_state_hash"]
    assert correction["state_hash"] == planned["resulting_state_hash"]
    assert body["reason"] not in str(activation)
    scope = {key: receipt[key] for key in ("world_id", "branch_id", "run_id")}
    successor = state_at(restarted, scope)
    assert successor.state_hash == correction["state_hash"]
    assert successor.projections["tabletop.entities"][target] == {
        **old_body,
        "hp": 15,
        "x": 4,
        "y": 2,
    }
    assert successor.projections["tabletop.spatial.positions"][target]["x"] == 4
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT c.command_type,c.resulting_state_hash,e.event_id
               FROM sim.command_log c JOIN sim.events e
                 ON (e.world_id,e.branch_id,e.run_id,e.actor_id,e.idempotency_key,e.event_type)=
                    (c.world_id,c.branch_id,c.run_id,c.actor_id,c.idempotency_key,c.command_type)
               JOIN sim.outbox o ON o.event_id=e.event_id
               WHERE c.branch_id=%s ORDER BY c.seq_id""",
            (scope["branch_id"],),
        )
        activation_entry, correction_entry = cursor.fetchall()
        assert activation_entry[:2] == (ACTIVATE_CAMPAIGN_REVISION, receipt["state_hash"])
        assert correction_entry == (
            "tabletop.timeline.correct",
            correction["state_hash"],
            correction["event_id"],
        )
        cursor.execute(
            "SELECT parameters FROM sim.command_log "
            "WHERE branch_id=%s AND command_type='tabletop.timeline.correct'",
            (scope["branch_id"],),
        )
        assert cursor.fetchall() == [(planned["request"],)]
        cursor.execute(
            "SELECT 1 FROM sim.event_perceptions WHERE event_id IN (%s,%s)",
            (activation_entry[2], correction_entry[2]),
        )
        assert cursor.fetchone() is None
        cursor.execute(
            "SELECT branch_id FROM sim.campaign_continuations WHERE world_id=%s",
            (scope["world_id"],),
        )
        assert cursor.fetchone() == (scope["branch_id"],)
    replay = operator.get(f"/api/v2/branches/{scope['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
    assert replay.get_json()["state_hash"] == correction["state_hash"]
    resume = operator.post(
        f"{root}/{body['request_id']}/resume",
        json={"request_id": str(uuid.uuid4()), "expected_epoch": 1},
    )
    assert resume.status_code == 200, resume.get_json()
    assert operator.post(activate).get_json() == activation


def test_031_upgrade_preserves_a_plain_prepared_revision(integration_stack, monkeypatch, tmp_path):
    stack = integration_stack
    name = "ttdm_planned_correction_upgrade_" + uuid.uuid4().hex
    owner = make_dsn(stack.admin_url, dbname=name)
    runtime = make_dsn(stack.database_url, dbname=name)
    old = replace(stack, admin_url=owner, database_url=runtime)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for item in discover(migrations)[:30]:
        shutil.copy2(migrations / item.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner, prior) == 30
            _, (admin, _, _, _, _, _, initial) = prepare(old, monkeypatch, tmp_path)
            plan = request_for(manual_capture(admin, initial))
            root = revision_path(initial)
            result = admin.post(root, json=plan)
            assert result.status_code == 200, result.get_json()
            assert "planned_correction" not in result.get_json()["provenance"]
            latest = migrations / "031_planned_campaign_corrections.sql"
            with closing(psycopg2.connect(owner)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute(
                    "SELECT to_regprocedure('sim.require_committed_planned_correction()')"
                )
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner, prior) == 1
            assert migrate(owner, prior) == 0
            _, operator = fresh_client(tmp_path)
            activated = operator.post(f"{root}/{plan['request_id']}/activate")
            assert activated.status_code == 200, activated.get_json()
            assert "correction" not in activated.get_json()["receipt"]
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
