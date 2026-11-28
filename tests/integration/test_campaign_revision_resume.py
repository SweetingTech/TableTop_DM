from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import psycopg2.errors
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import discover, migrate
from kernel import revision_resume
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_campaign_revision_plans import request_for, revision_path
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_section_g_campaign import handoff
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_tactical_choices import command

pytestmark = pytest.mark.integration


def activate_from(admin, base, checkpoint):
    plan = request_for(checkpoint)
    root = revision_path(base)
    prepared = admin.post(root, json=plan)
    assert prepared.status_code == 200, prepared.get_json()
    activated = admin.post(f"{root}/{plan['request_id']}/activate")
    assert activated.status_code == 200, activated.get_json()
    receipt = activated.get_json()["receipt"]
    return f"{root}/{plan['request_id']}/resume", {
        "world_id": receipt["world_id"],
        "branch_id": receipt["branch_id"],
        "run_id": receipt["run_id"],
    }


def test_resume_is_atomic_and_restarts_world_clock_and_controller(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, path, run, _witness, base) = prepare(stack, monkeypatch, tmp_path)
    original = handoff(player, path, run, 0, "AUTONOMOUS", "archive-controller-mode")
    resume, new = activate_from(admin, base, manual_capture(admin, base))
    clock_url = f"/api/v2/worlds/{new['world_id']}/branches/{new['branch_id']}/clock"
    control_url = path.replace(base["branch_id"], new["branch_id"]) + "/control"
    body = {"request_id": str(uuid.uuid4()), "expected_epoch": 1}
    initial = admin.get(clock_url).get_json()["clock"]
    assert initial["paused"] is True
    controller = player.get(control_url, query_string={"run_id": new["run_id"]}).get_json()[
        "control"
    ]
    assert controller["mode"] == "PAUSED"
    assert controller["epoch"] == 1
    assert player.post(resume, json=body).status_code == 403
    assert admin.post(resume, json={**body, "expected_epoch": 2}).status_code == 409

    resume_clock = revision_resume.PostgresRevisionResume._resume_clock

    def interrupted(*args):
        assert resume_clock(*args) is not None
        raise CheckpointHoldConflict("interrupted resume transaction")

    with monkeypatch.context() as patch:
        patch.setattr(revision_resume.PostgresRevisionResume, "_resume_clock", interrupted)
        failed = admin.post(resume, json=body)
    assert failed.status_code == 409, failed.get_json()
    assert failed.get_json()["details"] == "interrupted resume transaction"
    assert admin.get(clock_url).get_json()["clock"] == initial
    assert (
        player.get(control_url, query_string={"run_id": new["run_id"]}).get_json()["control"]
        == controller
    )

    restarted_app, restarted = fresh_client(tmp_path)
    result = restarted.post(resume, json=body)
    assert result.status_code == 200, result.get_json()
    receipt = result.get_json()
    assert receipt["autonomous_controllers"] == 1
    assert receipt["paused_controllers"] == 0
    assert receipt["clock_event_id"] is not None
    assert restarted.post(resume, json=body).get_json() == receipt
    assert restarted.post(resume, json={**body, "run_clock": False}).status_code == 409
    assert restarted.post(resume, json={**body, "request_id": str(uuid.uuid4())}).status_code == 409
    clock = restarted.get(clock_url).get_json()["clock"]
    assert clock["paused"] is False
    assert clock["epoch"] == initial["epoch"] + 1
    assert clock["seconds"] == initial["seconds"]
    restored = player.get(control_url, query_string={"run_id": new["run_id"]}).get_json()["control"]
    assert restored["epoch"] == 2
    assert restored["mode"] == "AUTONOMOUS"
    assert restored["owner_actor_id"] == original["owner_actor_id"]
    assert restored["executor_actor_id"] == original["executor_actor_id"]
    due = datetime.fromisoformat(clock["next_due"])
    assert restarted_app.extensions["world_runner"].run_once(due) == 1
    assert restarted.get(clock_url).get_json()["clock"]["seconds"] > initial["seconds"]
    assert restarted_app.extensions["character_runner"].run_once() == 1
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) FROM sim.command_log WHERE (world_id,branch_id,run_id)=(%s,%s,%s)
               AND decision_authorship='CHARACTER_POLICY'""",
            (new["world_id"], new["branch_id"], new["run_id"]),
        )
        assert cursor.fetchone() == (1,)
    with pytest.raises(
        psycopg2.errors.CheckViolation, match="canonical continuation was superseded"
    ):
        with transaction(
            actor_id=app.extensions["demo_ids"]["actor_id"], dsn=stack.database_url
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE cognition.mind_states SET mood='ALERT' "
                    "WHERE (world_id,branch_id,entity_id)=(%s,%s,%s)",
                    (base["world_id"], base["branch_id"], card["entity_id"]),
                )
    still_archived = command(
        player,
        base,
        card,
        "tabletop.dialogue.speak",
        {"text": "Old queued action"},
        "stale-on-resume",
    )
    assert still_archived.status_code == 409


def test_028_upgrade_can_resume_a_preexisting_paused_revision(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_resume_upgrade_" + uuid.uuid4().hex
    owner = make_dsn(stack.admin_url, dbname=name)
    runtime = make_dsn(stack.database_url, dbname=name)
    old = replace(stack, admin_url=owner, database_url=runtime)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for item in discover(migrations)[:27]:
        shutil.copy2(migrations / item.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner, prior) == 27
            _, (admin, player, _card, path, run, _witness, base) = prepare(
                old, monkeypatch, tmp_path
            )
            assignment = handoff(player, path, run, 0, "AUTONOMOUS", "archive-old-executor")
            resume, new = activate_from(admin, base, manual_capture(admin, base))
            latest = migrations / "028_campaign_revision_resume.sql"
            with closing(psycopg2.connect(owner)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_revision_resumes')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner, prior) == 1
            assert migrate(owner, prior) == 0
            _, restarted = fresh_client(tmp_path)
            with transaction(dsn=owner) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM sim.actor_capabilities "
                    "WHERE (world_id,actor_id,capability)=(%s,%s,'entity.act')",
                    (new["world_id"], assignment["executor_actor_id"]),
                )
                assert cursor.rowcount == 1
            result = restarted.post(
                resume,
                json={"request_id": str(uuid.uuid4()), "expected_epoch": 1, "run_clock": False},
            )
            assert result.status_code == 200, result.get_json()
            assert result.get_json()["clock_event_id"] is None
            assert result.get_json()["autonomous_controllers"] == 0
            assert result.get_json()["paused_controllers"] == 1
            url = f"/api/v2/worlds/{new['world_id']}/branches/{new['branch_id']}/clock"
            assert restarted.get(url).get_json()["clock"]["paused"] is True
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )


def test_player_without_controller_can_act_after_manual_resume(
    isolated_integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, _path, _run, _witness, base) = prepare(
        isolated_integration_stack, monkeypatch, tmp_path
    )
    resume, new = activate_from(admin, base, manual_capture(admin, base))

    def speak():
        return command(
            player, new, card, "tabletop.dialogue.speak", {"text": "Ready."}, "resume-fresh-action"
        )

    paused = speak()
    assert paused.status_code == 409, paused.get_json()
    body = {"request_id": str(uuid.uuid4()), "expected_epoch": 1, "run_clock": False}
    assert admin.post(resume, json=body).status_code == 200
    played = speak()
    assert played.status_code == 200, played.get_json()
    assert app.extensions["simulation"].worlds[uuid.UUID(new["world_id"])].continuation_epoch == 1
