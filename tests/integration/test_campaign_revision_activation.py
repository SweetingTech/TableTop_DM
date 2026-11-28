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

from cognition.control import EXECUTOR_CAPABILITIES, execution_actor
from cognition.postgres_narration import PostgresNarrations
from cognition.projector import WorldEventProjector
from infra.migrate import discover, migrate
from kernel import revision_activation
from kernel.campaign_activation import ACTIVATE_CAMPAIGN_REVISION
from kernel.campaign_revisions import revision_hold_id
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.control import ControlScope
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_campaign_revision_plans import request_for, revision_path
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_section_g_campaign import handoff
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
    app, (admin, player, card, path_to_body, run, witness, base) = prepare(
        stack, monkeypatch, tmp_path
    )
    original = handoff(player, path_to_body, run, 0, "HUMAN", "control-before-rewind")
    controlled = {**base, "control_epoch": original["epoch"]}
    seed_routine(app, admin, base, witness)
    prompt(admin, base, witness, "prompt-before-rewind")
    lines = {"text": "Hello friend.", "volume": "WHISPER"}
    prior = command(player, controlled, card, "tabletop.dialogue.speak", lines, "before-rewind")
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
        controlled,
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
    commit_activation = revision_activation.PostgresRevisionActivation._commit_activation

    def interrupted(*args):
        commit_activation(*args)
        raise CheckpointHoldConflict("interrupted test transaction")

    with monkeypatch.context() as patch:
        patch.setattr(
            revision_activation.PostgresRevisionActivation, "_commit_activation", interrupted
        )
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
    retry = command(player, controlled, card, "tabletop.dialogue.speak", lines, "before-rewind")
    assert retry.get_json()["event"] == prior.get_json()["event"]
    assert player_speech(player, controlled, card, "new-on-abandoned-branch").status_code == 409
    events = player.get(f"/api/v2/events?world_id={base['world_id']}").get_json()
    assert {event["branch_id"] for event in events} == {branch}
    assert all("funeral" not in str(event["payload"]) for event in events)
    assert all(event["event_type"] != ACTIVATE_CAMPAIGN_REVISION for event in events)
    assert (
        restarted.post(
            "/api/v2/commands",
            json={
                "world_id": receipt["world_id"],
                "branch_id": branch,
                "run_id": receipt["run_id"],
                "command_type": ACTIVATE_CAMPAIGN_REVISION,
            },
        ).status_code
        == 403
    )
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
            """SELECT c.run_id,c.input_origin,c.resulting_state_hash,c.parameters,e.payload,
                      e.visible_to::text[],e.observed_by::text[],o.payload->'perceptions'
               FROM sim.outbox o JOIN sim.events e ON o.event_id=e.event_id
               JOIN sim.command_log c
                 ON (e.world_id,e.branch_id,e.run_id,e.actor_id,e.idempotency_key)=
                    (c.world_id,c.branch_id,c.run_id,c.actor_id,c.idempotency_key)
               WHERE e.branch_id=%s AND e.event_type=%s AND c.command_type=%s""",
            (branch, ACTIVATE_CAMPAIGN_REVISION, ACTIVATE_CAMPAIGN_REVISION),
        )
        facts = {
            "source_branch_id": base["branch_id"],
            "source_checkpoint_id": plan["source_checkpoint_id"],
            "request_id": request["request_id"],
            "epoch": 1,
            "state_hash": receipt["state_hash"],
        }
        assert cursor.fetchall() == [
            (
                receipt["run_id"],
                "OPERATOR",
                receipt["state_hash"],
                facts,
                facts,
                [receipt["actor_id"]],
                [],
                [],
            )
        ]
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        with (
            transaction(
                actor_id=uuid.UUID(receipt["actor_id"]), dsn=stack.database_url
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """INSERT INTO sim.command_log
                   (command_id,command_type,command_version,world_id,branch_id,run_id,actor_id,
                    parameters,result,resulting_state_hash,idempotency_key,correlation_id,input_origin)
                   SELECT %s,command_type,command_version,world_id,branch_id,run_id,actor_id,
                          parameters,result,resulting_state_hash,'outside-activation',
                          correlation_id,input_origin
                   FROM sim.command_log WHERE branch_id=%s AND command_type=%s""",
                (str(uuid.uuid4()), branch, ACTIVATE_CAMPAIGN_REVISION),
            )
    successor = ControlScope(
        world_id=uuid.UUID(receipt["world_id"]),
        branch_id=uuid.UUID(branch),
        run_id=uuid.UUID(receipt["run_id"]),
        entity_id=uuid.UUID(observer),
    )
    new_path = path_to_body.replace(base["branch_id"], branch)
    restored = player.get(new_path + "/control", query_string={"run_id": receipt["run_id"]})
    assert restored.status_code == 200, restored.get_json()
    paused_controller = restored.get_json()["control"]
    assert paused_controller["mode"] == "PAUSED"
    assert paused_controller["executor_actor_id"] == str(execution_actor(successor))
    assert paused_controller["executor_actor_id"] != original["executor_actor_id"]
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT world_id,capability FROM sim.actor_capabilities WHERE actor_id=%s",
            (paused_controller["executor_actor_id"],),
        )
        assert set(cursor.fetchall()) == {
            (receipt["world_id"], capability) for capability in EXECUTOR_CAPABILITIES
        }
    for epoch, mode in ((1, "HUMAN"), (2, "AUTONOMOUS")):
        state = handoff(player, new_path, receipt["run_id"], epoch, mode, f"rewind-{mode}")
        assert state["executor_actor_id"] == paused_controller["executor_actor_id"]
        assert state["owner_actor_id"] == original["owner_actor_id"]
    _, cold = fresh_client(tmp_path)
    replay = cold.get(f"/api/v2/branches/{branch}/replay")
    assert replay.status_code == 200, replay.get_json()
    assert replay.get_json()["verified"] is True
    assert replay.get_json()["state_hash"] == receipt["state_hash"]
    assert uuid.UUID(replay.get_json()["branch_id"]) == uuid.UUID(branch)


def test_activation_fences_inflight_narration_and_rebuilds_character_retrieval(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    _, (admin, player, card, _, run, speaker, base) = prepare(stack, monkeypatch, tmp_path)
    earlier = "The sapphire ferry docks at noon."
    discarded = "The onyx funeral begins at sunrise."

    def speak(text, key):
        spoken = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": speaker,
                "command_type": "tabletop.dialogue.speak",
                "parameters": {"text": text},
                "idempotency_key": key,
            },
        )
        assert spoken.status_code == 200, spoken.get_json()

    roots = f"/api/v2/worlds/{base['world_id']}/branches"
    old_narration = f"{roots}/{base['branch_id']}/narration"
    observer = card["entity_id"]
    options = {"run_id": run, "audience": "CHARACTER", "observer_entity_id": observer}
    speak(earlier, "narration-before-checkpoint")
    audit = admin.post(old_narration, json={"run_id": run, "audience": "OPERATOR"})
    assert audit.status_code == 200, audit.get_json()
    earlier_entry = next(entry for entry in audit.get_json()["entries"] if earlier in entry["text"])
    observed = player.post(old_narration, json=options)
    assert observed.status_code == 200, observed.get_json()
    player_entry = observed.get_json()["entries"][0]
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT requester_actor_id FROM cognition.narration_entries WHERE narration_id=%s",
            (player_entry["narration_id"],),
        )
        player_actor = uuid.UUID(cursor.fetchone()[0])

    body = request_for(manual_capture(admin, base))
    speak(discarded, "narration-after-checkpoint")
    path = revision_path(base)
    prepared = admin.post(path, json=body)
    assert prepared.status_code == 200, prepared.get_json()
    retain = PostgresNarrations.retain

    def activate_before_retention(repository, entries, *, actor_id):
        assert any(discarded in entry.text for entry in entries)
        activation = admin.post(f"{path}/{body['request_id']}/activate")
        assert activation.status_code == 200, activation.get_json()
        return retain(repository, entries, actor_id=actor_id)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresNarrations, "retain", activate_before_retention)
        stale = player.post(old_narration, json=options)
    assert stale.status_code == 403, stale.get_json()
    assert discarded not in stale.get_data(as_text=True)
    narration_store = PostgresNarrations(stack.database_url)
    archived_player_entry = narration_store.get(
        uuid.UUID(base["world_id"]),
        uuid.UUID(base["branch_id"]),
        uuid.UUID(player_entry["narration_id"]),
        actor_id=player_actor,
    )
    assert archived_player_entry is None

    app, restarted_admin = fresh_client(tmp_path)
    assert restarted_admin.get(f"{old_narration}/{earlier_entry['narration_id']}").get_json() == (
        earlier_entry
    )
    archived_write = restarted_admin.post(
        old_narration, json={"run_id": run, "audience": "OPERATOR"}
    )
    assert archived_write.status_code == 403, archived_write.get_json()
    restarted_player = app.test_client()
    restarted_player.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    plan = prepared.get_json()
    successor = f"{roots}/{plan['successor_branch_id']}"
    rebuilt = restarted_player.post(
        f"{successor}/narration", json={**options, "run_id": plan["successor_run_id"]}
    )
    assert rebuilt.status_code == 200, rebuilt.get_json()
    assert earlier in rebuilt.get_data(as_text=True)
    assert discarded not in rebuilt.get_data(as_text=True)
    knowledge = f"{successor}/entities/{observer}/knowledge"
    recalled = restarted_player.get(knowledge, query_string={"query": "sapphire"})
    forgotten = restarted_player.get(knowledge, query_string={"query": "onyx"})
    assert recalled.status_code == forgotten.status_code == 200
    assert earlier in recalled.get_data(as_text=True)
    assert forgotten.get_json()["items"] == []


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
    with monkeypatch.context() as patch:
        patch.setattr(
            revision_activation.PostgresRevisionActivation, "_commit_activation", lambda *_: None
        )
        assert admin.post(activation).status_code == 409
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


def test_032_upgrade_preserves_archived_narration_and_rejects_new_entries(
    integration_stack, monkeypatch, tmp_path
):
    stack = integration_stack
    name = "ttdm_archive_narration_upgrade_" + uuid.uuid4().hex
    owner = make_dsn(stack.admin_url, dbname=name)
    runtime = make_dsn(stack.database_url, dbname=name)
    prior_stack = replace(stack, admin_url=owner, database_url=runtime)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for item in discover(migrations)[:31]:
        shutil.copy2(item.path, prior)

    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner, prior) == 31
            _, (admin, player, card, _, run, _, base) = prepare(prior_stack, monkeypatch, tmp_path)
            assert player_speech(player, base, card, "narration-before-upgrade").status_code == 200
            path = revision_path(base)
            body = request_for(manual_capture(admin, base))
            assert admin.post(path, json=body).status_code == 200
            assert admin.post(f"{path}/{body['request_id']}/activate").status_code == 200

            narration = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/narration"
            options = {"run_id": run, "audience": "OPERATOR"}
            stored = admin.post(narration, json=options)
            assert stored.status_code == 200, stored.get_json()
            entry = stored.get_json()["entries"][0]

            migration = migrations / "032_archive_narration_fence.sql"
            with closing(psycopg2.connect(owner)) as connection, connection.cursor() as cursor:
                cursor.execute(migration.read_text(encoding="utf-8"))
                connection.rollback()
            assert admin.post(narration, json=options).status_code == 200
            shutil.copy2(migration, prior)
            assert migrate(owner, prior) == 1
            assert migrate(owner, prior) == 0

            _, restarted = fresh_client(tmp_path)
            assert restarted.post(narration, json=options).status_code == 403
            saved = restarted.get(f"{narration}/{entry['narration_id']}")
            assert saved.status_code == 200 and saved.get_json() == entry
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
