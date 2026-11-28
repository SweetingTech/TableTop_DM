from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn
from psycopg2.extras import RealDictCursor

from domains.tabletop.world_time import CLOCK
from infra.migrate import discover, migrate
from kernel.campaign_checkpoints import CheckpointSection, FrozenComponent
from kernel.campaign_revisions import archived_runs, restored_run_id
from kernel.checkpoint_holds import CheckpointHoldConflict, PostgresCheckpointHolds
from kernel.checkpoint_knowledge import restore_knowledge
from kernel.database import transaction
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints
from kernel.state import stable_hash
from tests.integration.test_campaign_checkpoint_retention import (
    manual_capture,
    retention_path,
    scheduled_captures,
)
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_campaign_checkpoint_holds import player_speech
from tests.unit.kernel.test_tactical_choices import command

pytestmark = pytest.mark.integration


def revision_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/timeline-revision-plans"


def request_for(checkpoint_id, **updates):
    return {
        "request_id": str(uuid.uuid4()),
        "source_checkpoint_id": checkpoint_id,
        "expected_epoch": 0,
        "reason": "Correct the ferry captain's departure",
        **updates,
    }


def test_revision_plan_validates_the_archived_cut_and_preserves_current_play(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, _path, _run, _resident, base) = prepare(stack, monkeypatch, tmp_path)
    advance_clock(admin, base, 6)
    checkpoint_id = manual_capture(admin, base)
    world, branch = uuid.UUID(base["world_id"]), uuid.UUID(base["branch_id"])
    actor = app.extensions["demo_ids"]["actor_id"]
    archives = PostgresCampaignCheckpoints(
        stack.database_url,
        tmp_path / "campaign-checkpoints",
        PostgresCheckpointHolds(stack.database_url),
    )
    manifest, archived = archives.load(world, branch, uuid.UUID(checkpoint_id), actor)
    advance_clock(admin, base, 12)
    current = player_speech(player, base, card, "prior-to-revision-plan")
    assert current.status_code == 200, current.get_json()
    path = revision_path(base)
    body = request_for(checkpoint_id)
    response = player.post(path, json=body)
    assert response.status_code == 403
    assert body["reason"] not in response.get_data(as_text=True)
    assert admin.post(path, json={**body, "expected_epoch": 1}).status_code == 409
    assert (
        admin.post(path, json={**body, "source_checkpoint_id": str(uuid.uuid4())}).status_code
        == 404
    )
    assert (
        admin.post(path, json={**body, "source_live_run_id": str(uuid.uuid4())}).status_code == 409
    )
    first = admin.post(path, json=body)
    assert first.status_code == 200, first.get_json()
    assert first.headers["Cache-Control"] == "no-store"
    plan = first.get_json()
    assert plan["source_archive_hash"] == manifest.manifest.artifact_hash
    assert plan["provenance"]["source_state_hash"] == archived.boundary.state_hash
    assert plan["provenance"]["source_event_seq"] == archived.boundary.through_event_seq
    assert plan["provenance"]["source_command_ordinal"] == archived.boundary.command_ordinal
    assert plan["source_live_run_id"] == base["run_id"]
    assert plan["successor_branch_id"] != base["branch_id"]
    assert plan["successor_run_id"] != base["run_id"]
    assert plan["cancelled_at"] is None
    candidate = deepcopy(archived.projections)
    clock = candidate[CLOCK]["singleton"]
    assert clock["seconds"] == 6
    clock.update(
        run_id=plan["successor_run_id"],
        paused=True,
        epoch=clock["epoch"] + 1,
        step=0,
    )
    assert plan["candidate_state_hash"] == stable_hash(candidate)
    assert plan["candidate_state_hash"] != current.get_json()["state_hash"]

    _, restarted = fresh_client(tmp_path)
    plan_path = f"{path}/{body['request_id']}"
    assert restarted.get(plan_path).get_json() == plan
    assert player.get(plan_path).status_code == 403
    assert restarted.post(path, json=body).get_json() == plan
    assert restarted.post(path, json={**body, "reason": "Different request"}).status_code == 409
    actual_world = restarted.get(f"/api/v2/worlds/{world}").get_json()
    assert actual_world["state_hash"] == current.get_json()["state_hash"]
    assert actual_world["canonical_branch_id"] == str(branch)
    assert actual_world["continuation_epoch"] == 0


def test_revision_plan_holds_source_until_cancelled(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, _card, _path, _run, _resident, base) = prepare(
        stack, monkeypatch, tmp_path
    )
    oldest, _latest = scheduled_captures(stack, app, admin, base, [6, 12])
    policy = {"policy_id": str(uuid.uuid4()), "keep_automatic": 1}
    retention = retention_path(base)
    assert admin.put(retention, json=policy).status_code == 200
    path = revision_path(base)
    body = request_for(oldest, seed_policy="REUSE_CHECKPOINT_SEED")
    planned = admin.post(path, json=body)
    assert planned.status_code == 200, planned.get_json()
    assert admin.post(f"{retention}/apply", json={"policy_id": policy["policy_id"]}).get_json() == {
        "retired_checkpoint_ids": [],
        "cleanup_pending": 0,
    }
    actor = app.extensions["demo_ids"]["actor_id"]
    with transaction(actor_id=actor, dsn=stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT seed FROM sim.runs WHERE id=%s", (base["run_id"],))
            assert (cursor.fetchone()[0] or 0) == planned.get_json()["seed"]
    with pytest.raises(psycopg2.errors.CheckViolation, match="protected by a prepared revision"):
        with transaction(actor_id=actor, dsn=stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO sim.campaign_checkpoint_retention_state "
                    "(world_id,branch_id,checkpoint_id,actor_id,status,policy_id) "
                    "VALUES (%s,%s,%s,%s,'RETIRED',%s)",
                    (base["world_id"], base["branch_id"], oldest, str(actor), policy["policy_id"]),
                )
    player_actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    with transaction(actor_id=player_actor, dsn=stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM sim.campaign_revision_plans")
            assert cursor.fetchall() == []
    cancel_path = f"{path}/{body['request_id']}/cancel"
    assert player.post(cancel_path).status_code == 403
    cancelled = admin.post(cancel_path).get_json()
    assert cancelled["cancelled_at"] is not None
    assert admin.post(cancel_path).get_json() == cancelled
    assert admin.post(path, json=body).get_json() == cancelled
    assert admin.post(f"{retention}/apply", json={"policy_id": policy["policy_id"]}).get_json() == {
        "retired_checkpoint_ids": [oldest],
        "cleanup_pending": 0,
    }
    assert admin.post(path, json=request_for(oldest)).status_code == 409


def test_rewind_compiles_witnessed_knowledge_without_later_memories(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, _path, _run, witness, base) = prepare(stack, monkeypatch, tmp_path)
    before = player_speech(player, base, card, "before-the-recorded-cut")
    assert before.status_code == 200, before.get_json()
    earlier = before.get_json()["event"]["event_id"]
    checkpoint_id = manual_capture(admin, base)
    later_text = "The captain's funeral took place at dawn."
    after = command(
        player,
        base,
        card,
        "tabletop.dialogue.speak",
        {"text": later_text},
        "after-the-recorded-cut",
    )
    assert after.status_code == 200, after.get_json()
    later = after.get_json()["event"]["event_id"]
    response = admin.post(revision_path(base), json=request_for(checkpoint_id))
    assert response.status_code == 200, response.get_json()
    plan = response.get_json()
    branch = uuid.UUID(plan["successor_branch_id"])
    archives = PostgresCampaignCheckpoints(
        stack.database_url,
        tmp_path / "campaign-checkpoints",
        PostgresCheckpointHolds(stack.database_url),
    )
    actor = app.extensions["demo_ids"]["actor_id"]
    receipt, _ = archives.load(
        uuid.UUID(base["world_id"]), uuid.UUID(base["branch_id"]), uuid.UUID(checkpoint_id), actor
    )
    with transaction(actor_id=actor, dsn=stack.database_url) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            archived, evidence = archives.load_verified_at_cut(cursor, receipt.manifest)
    runs = {str(run): str(restored_run_id(branch, run)) for run in archived_runs(archived)}
    restored = restore_knowledge(archived, evidence, branch, runs)
    assert restored.digest == plan["provenance"]["retained_knowledge_hash"]
    assert restored == restore_knowledge(archived, evidence, branch, runs)
    assert later not in restored.event_origins
    restored_id = restored.event_origins[earlier]
    assert restored_id != earlier
    source_grant = next(
        row
        for row in evidence.perceptions
        if row["event_id"] == earlier and row["observer_entity_id"] == witness
    )
    restored_grant = next(
        row
        for row in restored.perceptions
        if row["event_id"] == restored_id and row["observer_entity_id"] == witness
    )
    assert restored_grant == {**source_grant, "event_id": restored_id, "branch_id": str(branch)}
    observation = next(
        row
        for row in restored.subjective["cognition.observations"]
        if row["source_event_id"] == restored_id and row["observer_entity_id"] == witness
    )
    assert observation["perceived_payload"]["text"] == "The ferry is ready."
    memory = next(
        row
        for row in restored.subjective["cognition.memories"]
        if row["source_event_id"] == restored_id and row["entity_id"] == witness
    )
    assert memory["source_observation_id"] == observation["id"]
    assert later_text not in str(restored.subjective)

    outside_cut = archived.model_copy(deep=True)
    minds = outside_cut.sections[CheckpointSection.MINDS]
    assert isinstance(minds, FrozenComponent)
    minds.data["cognition.observations"][0]["source_event_id"] = later
    with pytest.raises(CheckpointHoldConflict, match="outside the retained cut"):
        restore_knowledge(outside_cut, evidence, branch, runs)


def test_026_upgrade_preserves_existing_checkpoint_and_rolls_back_ddl(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_revision_plan_upgrade_" + uuid.uuid4().hex
    owner_url = make_dsn(stack.admin_url, dbname=name)
    runtime_url = make_dsn(stack.database_url, dbname=name)
    pending = replace(stack, admin_url=owner_url, database_url=runtime_url)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for migration in discover(migrations)[:25]:
        shutil.copy2(migrations / migration.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner_url, prior) == 25
            _, (admin, _player, _card, _path, _run, _resident, base) = prepare(
                pending, monkeypatch, tmp_path
            )
            checkpoint = manual_capture(admin, base)
            latest = migrations / "026_campaign_revision_plans.sql"
            with closing(psycopg2.connect(owner_url)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_revision_plans')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner_url, prior) == 1
            assert migrate(owner_url, prior) == 0
            _, restored = fresh_client(tmp_path)
            planned = restored.post(revision_path(base), json=request_for(checkpoint))
            assert planned.status_code == 200, planned.get_json()
            assert planned.get_json()["source_checkpoint_id"] == checkpoint
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
