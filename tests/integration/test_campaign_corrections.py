from __future__ import annotations

import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from time import monotonic, sleep

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from domains.tabletop.action_time import wait_seconds
from domains.tabletop.quests.contracts import QUESTS
from domains.tabletop.recovery import VITALS
from domains.tabletop.world_time import read_clock
from infra.migrate import discover, migrate
from kernel import revision_activation
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.database import transaction
from tests.integration.test_campaign_checkpoint_retention import manual_capture
from tests.integration.test_campaign_revision_plans import request_for, revision_path
from tests.integration.test_campaign_revision_resume import activate_from
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_quest_evidence_api import accepted, configure_quest
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.integration
CORRECT = "tabletop.timeline.correct"
RESURRECT = "tabletop.recovery.resurrect"


def submit(client, base, kind, parameters, key, *, body=None):
    return client.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": kind,
            "parameters": parameters,
            "idempotency_key": key,
            **({"embodied_entity_id": body} if body is not None else {}),
        },
    )


def state_at(app, scope):
    return app.extensions["world_runner"].snapshot().states.get(uuid.UUID(scope["branch_id"]))


def spawn(admin, base, actor, name, **state):
    target = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": target,
            "name": name,
            "entity_type": "NPC",
            "controller_actor_id": str(actor),
            "public_state": state,
        },
        f"spawn-{target}",
    )
    return target


def speak(admin, base, body, text, key):
    result = submit(admin, base, "tabletop.dialogue.speak", {"text": text}, key, body=body)
    assert result.status_code == 200, result.get_json()
    return result.get_json()["event"]["event_id"]


def memories(stack, base, observer):
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT COALESCE(origin.source_event_id,m.source_event_id),m.summary
               FROM cognition.memories m LEFT JOIN sim.campaign_revision_event_origins origin
               ON (origin.world_id,origin.branch_id,origin.event_id)=
                  (m.world_id,m.branch_id,m.source_event_id)
               WHERE (m.world_id,m.branch_id,m.entity_id)=(%s,%s,%s)""",
            (base["world_id"], base["branch_id"], observer),
        )
        return dict(cursor.fetchall())


def test_raid_death_resurrection_and_rewind_preserve_the_right_history(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, path, _run, neighbor, initial) = prepare(
        stack, monkeypatch, tmp_path
    )
    actor = app.extensions["demo_ids"]["actor_id"]
    observer = card["entity_id"]
    giver = spawn(
        admin,
        initial,
        actor,
        "Market captain",
        x=1,
        y=1,
        hp=2,
        max_hp=12,
        gold=10,
        inventory={"food": 2, "SPEAR": 1},
    )
    raiders = [
        spawn(
            admin,
            initial,
            actor,
            f"Raider {index}",
            x=index - 1,
            y=2,
            hp=10,
            max_hp=10,
            mana=8,
            max_mana=8,
            known_spells=["ARCANE_BOLT"],
        )
        for index in range(4)
    ]
    quest = configure_quest(
        admin,
        initial,
        giver,
        [{"kind": "MOVE", "description": "Watch the road", "x": -1, "y": 0}],
        items={"food": 1},
    )
    accepted(player, initial, card, quest)
    advice = speak(admin, initial, giver, "Watch the old market road, friend.", "market-advice")
    reaction = player.post(
        f"/api/v2/entities/{observer}/relationships",
        json={"target_entity_id": giver, "source_event_id": advice},
    )
    assert reaction.status_code == 201, reaction.get_json()
    before_state = state_at(app, initial)
    before_body = before_state.projections["tabletop.entities"][giver]
    before_quest = before_state.projections[QUESTS][quest]
    assert before_body["inventory"] == {"food": 1, "SPEAR": 1}
    assert before_body["gold"] == 3
    before_mind = memories(stack, initial, observer)
    assert advice in before_mind
    checkpoint = manual_capture(admin, initial)

    attacks = []
    for index, raider in enumerate(raiders):
        attack = submit(
            admin,
            initial,
            "tabletop.magic.invoke",
            {"spell_id": "ARCANE_BOLT", "target_id": giver},
            f"raid-cast-{index}",
            body=raider,
        )
        assert attack.status_code == 200, attack.get_json()
        attacks.append(attack.get_json()["event"]["event_id"])
    defeated = state_at(app, initial)
    assert defeated.projections["tabletop.entities"][giver]["dead"] is True
    vital = defeated.projections[VITALS][giver]
    assert vital["status"] == "DEAD" and vital["failures"] == 3
    funeral = speak(
        admin, initial, neighbor, "The captain's funeral was held at sunrise.", "funeral"
    )
    api_command(admin, initial, "tabletop.quest.cancel", {"quest_id": quest}, "raid-loss")
    revival = {"target_id": giver, "hit_points": 4}
    assert submit(player, initial, RESURRECT, revival, "unauthorized").status_code == 403
    assert (
        submit(admin, initial, RESURRECT, {**revival, "hit_points": 13}, "too-high").status_code
        == 400
    )
    revived = api_command(admin, initial, RESURRECT, revival, "captain-resurrection")
    assert (
        api_command(admin, initial, RESURRECT, revival, "captain-resurrection")["event"]
        == revived["event"]
    )
    assert submit(admin, initial, RESURRECT, revival, "already-living").status_code == 400
    revived_state = state_at(app, initial)
    resurrected = revived_state.projections["tabletop.entities"][giver]
    assert (resurrected["hp"], resurrected["dead"], resurrected["gold"]) == (4, False, 10)
    assert resurrected["inventory"] == {"food": 2, "SPEAR": 1}
    assert revived_state.projections[QUESTS][quest]["status"] == "CANCELLED"
    assert revived_state.projections[VITALS][giver] == {**vital, "status": "RECOVERED"}
    assert funeral in memories(stack, initial, observer)
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT source_event_id FROM cognition.observations "
            "WHERE branch_id=%s AND observer_entity_id=%s",
            (initial["branch_id"], observer),
        )
        experienced = {row[0] for row in cursor.fetchall()}
        assert {attacks[-1], funeral, revived["event"]["event_id"]} <= experienced

    plan = request_for(checkpoint)
    root = revision_path(initial)
    prepared = admin.post(root, json=plan)
    assert prepared.status_code == 200, prepared.get_json()
    activate = f"{root}/{plan['request_id']}/activate"
    persist = revision_activation.persist_restored_campaign

    def interrupted(*args):
        persist(*args)
        raise CheckpointHoldConflict("interrupted raid correction")

    with monkeypatch.context() as patch:
        patch.setattr(revision_activation, "persist_restored_campaign", interrupted)
        failed = admin.post(activate)
    assert failed.status_code == 409, failed.get_json()
    assert (
        admin.get(f"/api/v2/worlds/{initial['world_id']}").get_json()["canonical_branch_id"]
        == initial["branch_id"]
    )
    restarted, operator = fresh_client(tmp_path)
    activation = operator.post(activate)
    assert activation.status_code == 200, activation.get_json()
    receipt = activation.get_json()["receipt"]
    assert operator.post(activate).get_json() == activation.get_json()
    new = {key: receipt[key] for key in ("world_id", "branch_id", "run_id")}
    restored = state_at(restarted, new)
    assert restored.projections["tabletop.entities"][giver] == before_body
    assert restored.projections[QUESTS][quest] == {**before_quest, "run_id": new["run_id"]}
    assert memories(stack, new, observer) == before_mind
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM sim.branches WHERE world_id=%s "
            "AND branch_kind='CANONICAL' AND status='ACTIVE'",
            (initial["world_id"],),
        )
        assert cursor.fetchall() == [(new["branch_id"],)]
        cursor.execute(
            """SELECT branch_id,trust,familiarity FROM cognition.relationships
               WHERE source_entity_id=%s AND target_entity_id=%s ORDER BY branch_id""",
            (observer, giver),
        )
        relationships = {row[0]: row[1:] for row in cursor.fetchall()}
        assert relationships[new["branch_id"]] == relationships[initial["branch_id"]]
    assert funeral in memories(stack, initial, observer)

    patch = {
        "expected_epoch": 1,
        "expected_state_hash": restored.state_hash,
        "reason": "PRIVATE_CAPTAIN_CORRECTION",
        "corrections": [
            {"fact": "HIT_POINTS", "entity_id": giver, "hit_points": 6},
            {"fact": "POSITION", "entity_id": giver, "x": 2, "y": 1},
        ],
    }
    corrected = api_command(operator, new, CORRECT, patch, "corrected-captain")
    assert patch["reason"] not in str(corrected)
    assert corrected["result"]["result"] == {"epoch": 1, "corrected_facts": 2}
    updated = state_at(restarted, new)
    assert updated.projections["tabletop.entities"][giver] == {**before_body, "hp": 6, "x": 2}
    assert updated.projections["tabletop.spatial.positions"][giver]["x"] == 2
    with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT parameters->>'reason' FROM sim.command_log "
            "WHERE command_type=%s AND branch_id=%s",
            (CORRECT, new["branch_id"]),
        )
        assert cursor.fetchone() == (patch["reason"],)
        cursor.execute(
            "SELECT 1 FROM sim.event_perceptions WHERE event_id=%s",
            (corrected["event"]["event_id"],),
        )
        assert cursor.fetchone() is None
    resume = operator.post(
        f"{root}/{plan['request_id']}/resume",
        json={"request_id": str(uuid.uuid4()), "expected_epoch": 1},
    )
    assert resume.status_code == 200, resume.get_json()
    clock = read_clock(state_at(restarted, new))
    assert clock is not None and not clock.paused
    ready_at = clock.seconds + wait_seconds(updated, uuid.UUID(observer))
    while clock.seconds < ready_at:
        assert clock.next_due is not None
        assert restarted.extensions["world_runner"].run_once(clock.next_due) == 1
        advanced = read_clock(state_at(restarted, new))
        assert advanced is not None and advanced.seconds > clock.seconds
        clock = advanced
    scene = player.get(path.replace(initial["branch_id"], new["branch_id"]) + "/scene")
    assert scene.status_code == 200 and "funeral" not in scene.get_data(as_text=True)
    moved = command(player, new, card, "tabletop.spatial.move", {"dx": -1, "dy": 0}, "watch-road")
    assert moved.status_code == 200, moved.get_json()
    assert state_at(restarted, new).projections[QUESTS][quest]["status"] == "READY"
    replay = operator.get(f"/api/v2/branches/{new['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_correction_rejects_invalid_scope_authority_and_entire_invalid_batches(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, _, _, _, target, initial) = prepare(stack, monkeypatch, tmp_path)
    patch = {"fact": "HIT_POINTS", "entity_id": target, "hit_points": 6}
    original = {
        "expected_epoch": 1,
        "expected_state_hash": state_at(app, initial).state_hash,
        "reason": "Restore the correct count",
        "corrections": [patch],
    }
    assert submit(admin, initial, CORRECT, original, "ordinary-live").status_code == 409
    resume, new = activate_from(admin, initial, manual_capture(admin, initial))
    before = state_at(app, new)
    request = {**original, "expected_state_hash": before.state_hash}
    assert submit(player, new, CORRECT, request, "no-capability").status_code == 403
    assert (
        submit(admin, new, CORRECT, {**request, "expected_epoch": 2}, "wrong-epoch").status_code
        == 409
    )
    unknown = {"fact": "POSITION", "entity_id": str(uuid.uuid4()), "x": 1, "y": 2}
    for extra in (unknown, patch, {**patch, "fact": "INVENTORY"}):
        invalid = {**request, "corrections": [patch, extra]}
        rejected = submit(admin, new, CORRECT, invalid, "invalid-batch")
        assert rejected.status_code == 400, rejected.get_json()
        assert state_at(app, new).state_hash == before.state_hash
    corrected = api_command(admin, new, CORRECT, request, "valid")
    assert api_command(admin, new, CORRECT, request, "valid")["event"] == corrected["event"]
    assert submit(admin, new, CORRECT, request, "stale-hash").status_code == 409
    assert (
        admin.post(resume, json={"request_id": str(uuid.uuid4()), "expected_epoch": 1}).status_code
        == 200
    )
    now = {**request, "expected_state_hash": state_at(app, new).state_hash}
    assert submit(admin, new, CORRECT, now, "already-resumed").status_code == 409
    assert api_command(admin, new, CORRECT, request, "valid")["event"] == corrected["event"]


def test_correction_waits_for_run_before_locking_branch(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, _player, card, _path, _run, _witness, base) = prepare(stack, monkeypatch, tmp_path)
    _, new = activate_from(admin, base, manual_capture(admin, base))
    branch = (new["world_id"], new["branch_id"])
    body = {
        "expected_epoch": 1,
        "expected_state_hash": state_at(app, new).state_hash,
        "reason": "Repair the restored party member's health.",
        "corrections": [{"fact": "HIT_POINTS", "entity_id": card["entity_id"], "hit_points": 1}],
    }
    with ThreadPoolExecutor(max_workers=1) as workers:
        with transaction(dsn=stack.admin_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM sim.runs WHERE (world_id,branch_id,id)=(%s,%s,%s) "
                "FOR NO KEY UPDATE",
                (*branch, new["run_id"]),
            )
            pending = workers.submit(submit, admin, new, CORRECT, body, "concurrent-correction")
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if pending.done():
                    response = pending.result()
                    pytest.fail(f"correction returned before unlock: {response.status_code}")
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE %s = ANY(pg_blocking_pids(pid)))",
                    (connection.get_backend_pid(),),
                )
                if cursor.fetchone()[0]:
                    break
                sleep(0.02)
            else:
                pytest.fail("correction never waited for the run lock")
            cursor.execute(
                "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE NOWAIT",
                branch,
            )
        result = pending.result(timeout=10)
    assert result.status_code == 200, result.get_json()


def test_030_migration_upgrades_and_rolls_back_without_exposing_its_trigger(
    integration_stack, tmp_path
):
    stack = integration_stack
    name = "ttdm_correction_upgrade_" + uuid.uuid4().hex
    owner = make_dsn(stack.admin_url, dbname=name)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for item in discover(migrations)[:29]:
        shutil.copy2(migrations / item.version, prior)
    with closing(psycopg2.connect(stack.admin_url)) as maintenance:
        maintenance.autocommit = True
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            assert migrate(owner, prior) == 29
            latest = migrations / "030_campaign_corrections.sql"
            with closing(psycopg2.connect(owner)) as connection, connection.cursor() as cursor:
                cursor.execute(latest.read_text(encoding="utf-8"))
                connection.rollback()
                cursor.execute("SELECT to_regprocedure('sim.require_paused_campaign_correction()')")
                assert cursor.fetchone() == (None,)
            shutil.copy2(latest, prior)
            assert migrate(owner, prior) == 1
            assert migrate(owner, prior) == 0
            with transaction(dsn=owner) as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT has_function_privilege('tabletop_app',"
                    "'sim.require_paused_campaign_correction()','EXECUTE')"
                )
                assert cursor.fetchone() == (False,)
        finally:
            with maintenance.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
