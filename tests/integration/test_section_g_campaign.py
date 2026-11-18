from __future__ import annotations

import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import pytest

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_character_binding_api import setup_bound_character
from tests.unit.kernel.test_speech_combat_behavior import provoke
from tests.unit.kernel.test_tactical_choices import (
    command,
    establish_helper,
    record_support_choices,
)

pytestmark = pytest.mark.integration


def handoff(player, path, run, epoch, mode, key):
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": mode,
            "expected_epoch": epoch,
            "max_steps": 1,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["sensory_event"] is False
    return response.get_json()["state"]


def test_one_campaign_solo_mixed_and_all_autonomous(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("DATABASE_URL", stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    operator = app.test_client()
    operator.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = token
    scope = operator.post(
        "/api/v2/worlds", json={"name": "Campaign " + uuid.uuid4().hex}
    ).get_json()
    admin, player, card, game, path, run, _ = setup_bound_character(app, token, scope=scope)
    base = {"world_id": card["world_id"], "branch_id": scope["canonical_branch_id"], "run_id": run}

    # The campaign starts with one human seat and a real human action.
    for key, dx in (("solo-east", 1), ("solo-return", -1)):
        result = command(player, base, card, "tabletop.spatial.move", {"dx": dx, "dy": 0}, key)
        assert result.status_code == 200, result.get_json()
    _, quiet, second, _, quiet_path, quiet_run, _ = setup_bound_character(
        app,
        token,
        scope=scope,
        game=game,
        authored_identity={"backstory": "A peaceful traveler who seeks mercy and avoids violence."},
    )
    assert quiet_run == run
    helper = establish_helper(app, admin, base, card)
    examples = record_support_choices(app, admin, player, base, card, helper, helper)
    scene_args = {"run_id": run}
    before = player.get(path + "/context", query_string=scene_args).get_json()["situation"]
    mixed = handoff(player, path, run, 0, "AUTONOMOUS", "mixed-handoff")
    assert player.get(path + "/context", query_string=scene_args).get_json()["situation"] == before
    assert quiet.get(quiet_path + "/control", query_string=scene_args).get_json()["control"] is None
    workers = [create_app(artifact_root=tmp_path) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda worker: worker.extensions["character_runner"].run_once(), workers))

    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.actor_id::text,c.parameters->>'target_id',p.payload->'choices' "
            "FROM sim.command_log c "
            "JOIN sim.events e USING(world_id,branch_id,run_id,actor_id,idempotency_key) "
            "JOIN cognition.character_proposal_receipts p ON p.decision_id=e.decision_trace_id "
            "WHERE c.run_id=%s AND c.input_origin='STAND_IN'",
            (run,),
        )
        [(executor, target, profile)] = cursor.fetchall()
        assert executor == mixed["executor_actor_id"] and target == helper
        assert profile["player_actor_id"] == mixed["owner_actor_id"] != executor
        assert profile["character_id"] == card["character_id"]
        assert set(profile["evidence_event_ids"]) == examples

    # A history-free companion sees a threat and applies the pinned peaceful backstory.
    provoke(admin, base, helper, second, "companion-threat")
    own_choices = quiet.get(quiet_path + "/choice-profile", query_string=scene_args).get_json()
    assert own_choices["comparable_count"] == 0
    before = quiet.get(quiet_path + "/context", query_string=scene_args).get_json()["situation"]
    handoff(player, path, run, mixed["epoch"], "AUTONOMOUS", "rich-standin-next")
    companion = handoff(quiet, quiet_path, run, 0, "AUTONOMOUS", "companion-handoff")
    assert (
        quiet.get(quiet_path + "/context", query_string=scene_args).get_json()["situation"]
        == before
    )
    worker = create_app(artifact_root=tmp_path)
    projector = WorldEventProjector(stack.database_url)
    deadline = time.monotonic() + 8
    steps = 0
    while steps < 2 and time.monotonic() < deadline:
        projector.run_once(limit=100)
        steps += worker.extensions["character_runner"].run_once()
        if steps < 2:
            time.sleep(0.05)
    assert steps == 2

    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT embodied_entity_id::text,actor_id::text,command_type,parameters->>'text' "
            "FROM sim.command_log WHERE run_id=%s AND input_origin='STAND_IN'",
            (run,),
        )
        moves = cursor.fetchall()
        assert [row[0] for row in moves].count(card["entity_id"]) == 2
        [(body, executor, action, line)] = [row for row in moves if row[0] == second["entity_id"]]
        assert executor == companion["executor_actor_id"] != companion["owner_actor_id"]
        assert action == "tabletop.dialogue.speak" and "want to fight" in line
        cursor.execute(
            "SELECT player_actor_id::text,event_id::text FROM cognition.human_choice_evidence "
            "WHERE run_id=%s",
            (run,),
        )
        assert set(cursor.fetchall()) == {(mixed["owner_actor_id"], event) for event in examples}

    handoff(quiet, quiet_path, run, companion["epoch"], "HUMAN", "return-to-companion")
    assert (
        quiet.get(quiet_path + "/control", query_string=scene_args).get_json()["control"]["mode"]
        == "HUMAN"
    )


def test_trial_and_typed_direction_never_train_canonical_player_profile(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, path, run, _, base) = prepare(stack, monkeypatch, tmp_path)
    helper = establish_helper(app, admin, base, card)
    examples = record_support_choices(app, admin, player, base, card, helper, helper)
    direction = app.extensions["simulation"].submit(
        CommandProposal(
            **{key: uuid.UUID(value) for key, value in base.items()},
            actor_id=app.extensions["demo_ids"]["actor_id"],
            embodied_entity_id=uuid.UUID(helper),
            command_type="tabletop.combat.guard",
            input_origin="DIRECTOR",
            idempotency_key="trusted-direction",
        )
    )
    assert "input_origin" not in direction.event.model_dump()
    WorldEventProjector(stack.database_url).run_once(limit=100)
    before = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert set(before["evidence_event_ids"]) == examples

    saved = admin.post(f"/api/v2/worlds/{base['world_id']}/snapshots", json={})
    assert saved.status_code == 201, saved.get_json()
    revision = admin.post(
        f"/api/v2/snapshots/{saved.get_json()['snapshot_id']}/branches", json={"seed": 438}
    )
    assert revision.status_code == 201, revision.get_json()
    trial = revision.get_json()
    trial_run = trial["run"]["run_id"]
    trial_choice = command(
        player,
        {**base, "branch_id": trial["branch_id"], "run_id": trial_run},
        card,
        "tabletop.magic.invoke",
        {"spell_id": "MEND", "target_id": helper},
        "alternate-history",
    )
    assert trial_choice.status_code == 200, trial_choice.get_json()
    restored = create_app(artifact_root=tmp_path).test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    after = restored.get(path + "/choice-profile", query_string={"run_id": run})
    assert after.get_json() == before
    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT idempotency_key,input_origin FROM sim.command_log "
            "WHERE idempotency_key IN ('trusted-direction','alternate-history')",
        )
        assert set(cursor.fetchall()) == {
            ("trusted-direction", "DIRECTOR"),
            ("alternate-history", "HUMAN_INPUT"),
        }
        cursor.execute(
            "SELECT event_id::text FROM cognition.human_choice_evidence WHERE world_id=%s",
            (base["world_id"],),
        )
        assert {row[0] for row in cursor.fetchall()} == examples
