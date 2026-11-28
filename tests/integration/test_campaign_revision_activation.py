from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import psycopg2.errors
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from cognition.projector import WorldEventProjector
from infra.migrate import discover, migrate
from kernel import revision_activation
from kernel.campaign_revisions import revision_hold_id
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_campaign_revision_plans import request_for, revision_path
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_campaign_checkpoint_holds import hold_path, player_speech
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_speech_combat_behavior import prompt
from tests.unit.kernel.test_tactical_choices import command

pytestmark = pytest.mark.integration


def test_revision_rolls_back_then_restores_witness_and_population_after_restart(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, _path, _run, witness, base) = prepare(stack, monkeypatch, tmp_path)
    seed_routine(app, admin, base, witness)
    prompt(admin, base, witness, "prompt-before-rewind")
    lines = {"text": "Hello friend.", "volume": "WHISPER"}
    prior = command(player, base, card, "tabletop.dialogue.speak", lines, "before-rewind")
    assert prior.status_code == 200, prior.get_json()
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM cognition.human_choice_evidence WHERE event_id=%s",
            (prior.get_json()["event"]["event_id"],),
        )
        assert cursor.fetchone() == (1,)
    checkpoint = manual_capture(admin, base)
    after = command(
        player,
        base,
        card,
        "tabletop.dialogue.speak",
        {"text": "The captain's funeral was held at sunrise."},
        "after-rewind-cut",
    )
    assert after.status_code == 200, after.get_json()
    request = request_for(checkpoint)
    path = revision_path(base)
    received = admin.post(path, json=request)
    assert received.status_code == 200, received.get_json()
    plan = received.get_json()
    url = f"{path}/{request['request_id']}/activate"
    assert player.post(url).status_code == 403
    persist = revision_activation.persist_restored_campaign

    def interrupted(*args):
        persist(*args)
        raise CheckpointHoldConflict("interrupted test transaction")

    with monkeypatch.context() as patch:
        patch.setattr(revision_activation, "persist_restored_campaign", interrupted)
        failed = admin.post(url)
    assert failed.status_code == 409, failed.get_json()
    assert failed.get_json()["details"] == "interrupted test transaction"
    assert admin.get(hold_path(base)).get_json()["status"] == "READY"
    assert (
        admin.get(f"/api/v2/worlds/{base['world_id']}").get_json()["canonical_branch_id"]
        == base["branch_id"]
    )

    _, restarted = fresh_client(tmp_path)
    activation = restarted.post(url)
    assert activation.status_code == 200, activation.get_json()
    result = activation.get_json()
    assert result["phase"] == "COMMITTED"
    receipt = result["receipt"]
    branch = receipt["branch_id"]
    assert (branch, receipt["run_id"], receipt["epoch"], receipt["state_hash"]) == (
        plan["successor_branch_id"],
        plan["successor_run_id"],
        1,
        plan["candidate_state_hash"],
    )
    assert restarted.post(url).get_json() == result
    assert restarted.post(f"{path}/{request['request_id']}/cancel").status_code == 409
    assert restarted.get(f"/api/v2/worlds/{base['world_id']}").get_json()[
        "canonical_branch_id"
    ] == (branch)
    retry = command(player, base, card, "tabletop.dialogue.speak", lines, "before-rewind")
    assert retry.get_json()["event"] == prior.get_json()["event"]
    assert player_speech(player, base, card, "new-on-abandoned-branch").status_code == 409
    events = player.get(f"/api/v2/events?world_id={base['world_id']}").get_json()
    assert {event["branch_id"] for event in events} == {branch}
    assert all("funeral" not in str(event["payload"]) for event in events)
    observer = card["entity_id"]
    scene = f"/api/v2/worlds/{base['world_id']}/branches"
    assert player.get(f"{scene}/{base['branch_id']}/entities/{observer}/scene").status_code == 403
    restored_scene = player.get(f"{scene}/{branch}/entities/{observer}/scene")
    assert restored_scene.status_code == 200, restored_scene.get_json()
    assert "funeral" not in restored_scene.get_data(as_text=True)
    archived_narration = player.post(
        f"{scene}/{base['branch_id']}/narration",
        json={"run_id": base["run_id"], "audience": "CHARACTER", "observer_entity_id": observer},
    )
    assert archived_narration.status_code == 403
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM sim.branches WHERE world_id=%s AND status='ACTIVE' "
            "AND branch_kind='CANONICAL'",
            (base["world_id"],),
        )
        assert cursor.fetchall() == [(branch,)]
        cursor.execute(
            """SELECT origin.source_event_id, observation.perceived_payload
               FROM cognition.observations observation
               JOIN sim.campaign_revision_event_origins origin ON
                (origin.world_id,origin.branch_id,origin.event_id)=
                (observation.world_id,observation.branch_id,observation.source_event_id)
               WHERE observation.branch_id=%s AND observation.observer_entity_id=%s""",
            (branch, witness),
        )
        known = cursor.fetchall()
        assert any(row[0] == prior.get_json()["event"]["event_id"] for row in known)
        assert all(row[0] != after.get_json()["event"]["event_id"] for row in known)
        cursor.execute(
            "SELECT count(*) FROM population.materialized_people "
            "WHERE branch_id=%s AND entity_id=%s",
            (branch, witness),
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            """SELECT origin.source_event_id FROM cognition.human_choice_evidence evidence
               JOIN sim.campaign_revision_event_origins origin
                 ON (origin.world_id,origin.branch_id,origin.event_id)=
                    (evidence.world_id,evidence.branch_id,evidence.event_id)
               WHERE evidence.branch_id=%s""",
            (branch,),
        )
        authored = {row[0] for row in cursor.fetchall()}
        assert prior.get_json()["event"]["event_id"] in authored
        assert after.get_json()["event"]["event_id"] not in authored
        cursor.execute(
            "SELECT count(*) FROM sim.outbox o JOIN sim.events e ON o.event_id=e.event_id "
            "WHERE e.branch_id=%s",
            (branch,),
        )
        assert cursor.fetchone() == (0,)
    _, cold = fresh_client(tmp_path)
    replay = cold.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200, replay.get_json()
    assert replay.get_json()["verified"] is True
    assert replay.get_json()["state_hash"] == receipt["state_hash"]
    assert uuid.UUID(replay.get_json()["branch_id"]) == uuid.UUID(branch)


def test_activation_keeps_live_hold_until_projected_and_rejects_half_switch(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, _path, _run, _witness, base) = prepare(stack, monkeypatch, tmp_path)
    request = request_for(manual_capture(admin, base))
    path = revision_path(base)
    planned = admin.post(path, json=request)
    assert planned.status_code == 200, planned.get_json()
    actor = app.extensions["demo_ids"]["actor_id"]
    with monkeypatch.context() as patch:
        patch.setattr(app.extensions["simulation"], "subjective_projector", None)
        pending = player_speech(player, base, card, "before-activation-drain")
    assert pending.status_code == 200, pending.get_json()
    activation = f"{path}/{request['request_id']}/activate"
    waiting = admin.post(activation)
    assert waiting.status_code == 202, waiting.get_json()
    assert waiting.get_json()["pending_events"] == 1
    assert player_speech(player, base, card, "held-during-drain").status_code == 409

    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"
    assert WorldEventProjector(stack.database_url).run_once(topic=topic) == 1
    with pytest.raises(psycopg2.errors.IntegrityError):
        with transaction(actor_id=actor, dsn=stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT sim.start_campaign_revision(%s,%s,%s,%s,%s)",
                    (
                        base["world_id"],
                        base["branch_id"],
                        request["request_id"],
                        str(revision_hold_id(uuid.UUID(request["request_id"]))),
                        planned.get_json()["candidate_state_hash"],
                    ),
                )
    assert admin.get(hold_path(base)).get_json()["status"] == "READY"
    cancelled = admin.post(f"{path}/{request['request_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.get_json()
    assert admin.get(hold_path(base)).get_json() == {"hold": None}
    assert player_speech(player, base, card, "held-during-drain").status_code == 200


def test_027_upgrade_activates_a_prepared_plan_and_rolls_back_ddl(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_revision_commit_upgrade_" + uuid.uuid4().hex
    owner = make_dsn(stack.admin_url, dbname=name)
    runtime = make_dsn(stack.database_url, dbname=name)
    pending = replace(stack, admin_url=owner, database_url=runtime)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for item in discover(migrations)[:26]:
        shutil.copy2(migrations / item.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner, prior) == 26
            _, (admin, _player, _card, _path, _run, _witness, base) = prepare(
                pending, monkeypatch, tmp_path
            )
            body = request_for(manual_capture(admin, base))
            path = revision_path(base)
            prepared = admin.post(path, json=body)
            assert prepared.status_code == 200, prepared.get_json()
            artifact = migrations / "027_campaign_revision_activation.sql"
            with closing(psycopg2.connect(owner)) as connection, connection.cursor() as cursor:
                cursor.execute(artifact.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regclass('sim.campaign_revision_commits')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(artifact, prior)
            assert migrate(owner, prior) == 1
            assert migrate(owner, prior) == 0
            _, restarted = fresh_client(tmp_path)
            activated = restarted.post(f"{path}/{body['request_id']}/activate")
            assert activated.status_code == 200, activated.get_json()
            assert (
                activated.get_json()["receipt"]["branch_id"]
                == prepared.get_json()["successor_branch_id"]
            )
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
