from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg2
import pytest
from pydantic import ValidationError

from cognition.behavior import BehaviorProfile
from cognition.choices import ChoiceProfile
from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from kernel.control import ControllerState
from kernel.errors import AuthorizationDenied
from kernel.state import stable_hash
from tests.integration.test_section_g_campaign import handoff
from tests.integration.test_speech_combat_behavior import prepare, provoke
from tests.unit.kernel.test_character_binding_api import setup_bound_character
from tests.unit.kernel.test_tactical_choices import (
    establish_helper,
    record_support_choices,
    resources,
)

pytestmark = pytest.mark.integration


def test_durable_human_choice_records_only_the_characters_known_threats(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, _, run, visible, base) = prepare(stack, monkeypatch, tmp_path)
    hidden_name = "Invisible assailant"
    secret = "Synthetic private ambush motive"
    spawned = admin.post(
        f"/api/v2/worlds/{base['world_id']}/entities",
        json={
            "world_id": base["world_id"],
            "branch_id": base["branch_id"],
            "name": hidden_name,
            "entity_type": "NPC",
            "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
            "public_state": {
                "x": 0,
                "y": 1,
                "hp": 100,
                "max_hp": 100,
                "reach": 1,
                "invisible": True,
                "damage_bonus": -10,
            },
            "secret_state": {"motive": secret},
        },
    )
    assert spawned.status_code == 201, spawned.get_json()
    hidden = spawned.get_json()["entity_id"]
    provoke(admin, base, hidden, card, "hidden-attack")
    provoke(admin, base, visible, card, "visible-attack")
    WorldEventProjector(stack.database_url).run_once(limit=100)

    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.combat.attack",
            "parameters": {"target_id": visible},
            "seed": 2,
            "idempotency_key": "human-choice",
        },
    )
    assert response.status_code == 200, response.get_json()
    outcome = response.get_json()["event"]

    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT e.payload->>'attacker_id', o.perceived_payload "
            "FROM cognition.observations o JOIN sim.events e ON e.event_id=o.source_event_id "
            "WHERE e.run_id=%s AND e.idempotency_key='hidden-attack' AND o.observer_entity_id=%s",
            (run, card["entity_id"]),
        )
        assert cursor.fetchall() == [(hidden, {"summary": "Sounds of nearby fighting."})]
        cursor.execute(
            "SELECT h.payload,c.input_origin,c.decision_authorship,c.committed_revision, "
            "c.actor_id::text,b.binding_id::text,e.payload->>'target_id' "
            "FROM cognition.human_choice_evidence h "
            "JOIN sim.events e USING(world_id,branch_id,run_id,event_id) "
            "JOIN sim.command_log c USING(world_id,branch_id,run_id,actor_id,idempotency_key) "
            "JOIN tabletop.character_bindings b "
            "USING(world_id,branch_id,run_id,entity_id,character_id,binding_id) "
            "WHERE h.run_id=%s AND h.event_id=%s AND h.entity_id=%s AND h.character_id=%s",
            (run, outcome["event_id"], card["entity_id"], card["character_id"]),
        )
        [(evidence, origin, author, revision, actor, binding, target)] = cursor.fetchall()

    assert (origin, author, target) == ("HUMAN_INPUT", "HUMAN", visible)
    assert evidence["player_actor_id"] == actor == outcome["actor_id"]
    assert evidence["binding_id"] == binding
    assert evidence["projection_version"] == revision - 1
    chosen = f"attack:{visible}"
    assert evidence["chosen_key"] == chosen
    assert chosen in {option["key"] for option in evidence["options"]}
    assert [threat["entity_id"] for threat in evidence["frame"]["threats"]] == [visible]
    serialized = json.dumps(evidence)
    assert all(value not in serialized for value in (hidden, hidden_name, secret))


def test_versioned_profiles_rebuild_without_learning_stand_in_actions(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, player, card, path, run, _, base) = prepare(stack, monkeypatch, tmp_path)
    helper = establish_helper(app, admin, base, card)
    examples = record_support_choices(app, admin, player, base, card, helper, helper)
    query = {"run_id": run}
    expected_profiles = {
        "behavior-profile": (BehaviorProfile, "movement-behavior-1.0.0"),
        "choice-profile": (ChoiceProfile, "speech-combat-behavior-1.4.0"),
    }
    initial_choice = player.get(path + "/choice-profile", query_string=query).get_json()
    leave = handoff(player, path, run, 0, "AUTONOMOUS", "proof-history-leave")
    assert app.extensions["character_runner"].run_once() == 1
    handoff(player, path, run, leave["epoch"], "HUMAN", "proof-history-return")
    resources(app, admin, base, helper)
    WorldEventProjector(stack.database_url).run_once(limit=100)
    rebuilt = {}
    for endpoint, (model, version) in expected_profiles.items():
        response = player.get(f"{path}/{endpoint}", query_string=query)
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload["version"] == version
        assert payload["player_actor_id"] == leave["owner_actor_id"]
        assert payload["character_id"] == card["character_id"]
        assert payload["profile_id"] == stable_hash(
            {key: value for key, value in payload.items() if key != "profile_id"}
        )
        with pytest.raises(ValidationError, match="version differs|content differs"):
            model.model_validate({**payload, "version": "changed-without-rehash"})
        rebuilt[endpoint] = payload

    # A fresh process derives both profiles from retained input and the current scene.
    restarted = create_app(artifact_root=tmp_path).test_client()
    restarted.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    for endpoint, payload in rebuilt.items():
        restored = restarted.get(f"{path}/{endpoint}", query_string=query)
        assert restored.status_code == 200, restored.get_json()
        assert restored.get_json() == payload
    after = rebuilt["choice-profile"]
    assert after["profile_id"] != initial_choice["profile_id"]
    assert set(after["evidence_event_ids"]) == examples
    assert after["comparable_count"] == after["action_sample_counts"][f"spell:MEND:{helper}"] == 4
    assert after["confidence"] == pytest.approx(4 / 7)

    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT e.event_id::text,c.input_origin,c.actor_id::text,h.payload->>'version' "
            "FROM sim.command_log c JOIN sim.events e "
            "USING(world_id,branch_id,run_id,actor_id,idempotency_key) "
            "LEFT JOIN cognition.human_choice_evidence h ON h.event_id=e.event_id "
            "WHERE c.run_id=%s AND c.input_origin IN ('HUMAN_INPUT','STAND_IN')",
            (run,),
        )
        rows = set(cursor.fetchall())
    assert {row for row in rows if row[1] == "HUMAN_INPUT"} == {
        (event, "HUMAN_INPUT", leave["owner_actor_id"], "speech-combat-behavior-1.3.0")
        for event in examples
    }
    [(stand_in_event, origin, executor, evidence_version)] = [
        row for row in rows if row[1] == "STAND_IN"
    ]
    assert (origin, executor, evidence_version) == ("STAND_IN", leave["executor_actor_id"], None)
    assert stand_in_event not in after["evidence_event_ids"]


def test_atomic_takeover_allows_one_epoch_and_only_its_new_controller(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (_, player, card, path, run, _, base) = prepare(stack, monkeypatch, tmp_path)
    leave = handoff(player, path, run, 0, "AUTONOMOUS", "proof-exclusive-leave")
    controller = ControllerState.model_validate(leave)
    old_action = (
        app.extensions["character_decisions"]
        .decide(controller.scope, controller.executor_actor_id, controller.decision_key, controller)
        .outcome.proposal
    )
    human_action = {
        **base,
        "embodied_entity_id": card["entity_id"],
        "control_epoch": 1,
        "command_type": "tabletop.spatial.move",
        "parameters": {"dx": -1, "dy": 0},
        "idempotency_key": "proof-exclusive-human",
    }
    denied = player.post("/api/v2/commands", json=human_action)
    assert denied.status_code == 403, denied.get_json()
    cookie = player.get_cookie("ttdm_session").value
    ready = Barrier(2, timeout=10)

    def take(key):
        contender = app.test_client()
        contender.set_cookie("ttdm_session", cookie)
        ready.wait()
        return contender.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "HUMAN",
                "expected_epoch": 1,
                "max_steps": 1,
                "idempotency_key": key,
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(take, ("proof-take-a", "proof-take-b")))
    assert sorted(result.status_code for result in results) == [200, 409]
    winner = next(result.get_json()["state"] for result in results if result.status_code == 200)
    assert (winner["epoch"], winner["mode"], winner["owner_actor_id"]) == (
        2,
        "HUMAN",
        leave["owner_actor_id"],
    )
    assert (
        player.get(path + "/control", query_string={"run_id": run}).get_json()["control"] == winner
    )

    ready = Barrier(2, timeout=10)

    def stale_worker():
        source = app.extensions["character_runner"].snapshot()
        ready.wait()
        with pytest.raises(AuthorizationDenied):
            source.submit(old_action)

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale = pool.submit(stale_worker)
        ready.wait()
        committed = player.post("/api/v2/commands", json={**human_action, "control_epoch": 2})
        stale.result(timeout=15)
    assert committed.status_code == 200, committed.get_json()
    with psycopg2.connect(stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT payload->'state'->>'epoch',payload->'state'->>'mode' "
            "FROM cognition.controller_handoffs WHERE run_id=%s AND entity_id=%s",
            (run, card["entity_id"]),
        )
        assert sorted(cursor.fetchall()) == [("1", "AUTONOMOUS"), ("2", "HUMAN")]
        cursor.execute(
            "SELECT input_origin,actor_id::text FROM sim.command_log "
            "WHERE run_id=%s AND embodied_entity_id=%s AND command_type='tabletop.spatial.move'",
            (run, card["entity_id"]),
        )
        assert cursor.fetchall() == [("HUMAN_INPUT", leave["owner_actor_id"])]


def test_control_recap_enforces_current_world_body_and_run_authority(
    isolated_integration_stack, monkeypatch, tmp_path
):
    stack = isolated_integration_stack
    app, (admin, owner, card, path, run, _, base) = prepare(stack, monkeypatch, tmp_path)
    _, other, _, _, other_path, _, _ = setup_bound_character(
        app,
        scope={
            "world_id": base["world_id"],
            "canonical_branch_id": base["branch_id"],
            "current_run_id": run,
        },
    )
    assert other.get(other_path + "/control", query_string={"run_id": run}).status_code == 200
    leave = handoff(owner, path, run, 0, "AUTONOMOUS", "proof-recap-leave")
    assert app.extensions["character_runner"].run_once() == 1
    handoff(owner, path, run, leave["epoch"], "HUMAN", "proof-recap-return")
    WorldEventProjector(stack.database_url).run_once(limit=100)

    recap = path + "/control/recap"
    query = {"run_id": run}
    response = owner.get(recap, query_string=query)
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    data = response.get_json()
    assert data["available"] and len(data["entries"]) == 1
    [witnessed] = data["entries"]
    assert witnessed["audience"] == "CHARACTER"
    assert witnessed["observer_entity_id"] == card["entity_id"]
    managed = admin.get(recap, query_string=query)
    assert managed.status_code == 200 and managed.get_json()["available"]
    [operator_entry] = managed.get_json()["entries"]
    for field in ("audience", "observer_entity_id", "source_event_id", "text"):
        assert operator_entry[field] == witnessed[field]
    for rejected in (
        other.get(recap, query_string=query),
        app.test_client().get(recap, query_string=query),
        owner.get(recap, query_string={"run_id": str(uuid.uuid4())}),
    ):
        assert rejected.status_code in {401, 403}, rejected.get_json()
        assert witnessed["source_event_id"] not in rejected.get_data(as_text=True)
        assert "entries" not in rejected.get_json()
