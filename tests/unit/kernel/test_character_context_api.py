from __future__ import annotations

import os
import uuid

import pytest

from kernel.api.app import create_app
from tests.unit.cognition.test_relationship_api import physical_relationship_game
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def test_knowledge_waits_for_sensory_projection_and_retry_projects_once(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    client, base, controller, observer, target, speak = physical_relationship_game(app, admin)
    simulation = app.extensions["simulation"]
    original = simulation.subjective_projector
    simulation.configure_subjective_projector(lambda receipt: None)
    first = speak("delayed-knowledge")
    endpoint = (
        f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}"
        f"/entities/{observer}/knowledge"
    )
    headers = {"X-TTDM-Actor-ID": controller}
    pending = client.get(endpoint, headers=headers, query_string={"query": "neighbor"})
    assert pending.status_code == 409, pending.get_json()
    before = len(simulation.events)
    assert original is not None
    simulation.configure_subjective_projector(original)
    assert speak("delayed-knowledge") == first
    assert len(simulation.events) == before
    ready = client.get(endpoint, headers=headers, query_string={"query": "neighbor"})
    assert ready.status_code == 200, ready.get_json()
    assert [item["text"] for item in ready.get_json()["items"]] == ["Hello, neighbor."]


def check_pinned_knowledge(app, *, scope=None):
    admin, player, card, game, path, run, user = setup_bound_character(app, scope=scope)
    endpoint = path + "/knowledge"
    response = player.get(endpoint, query_string={"run_id": run, "query": "ferry"})
    assert response.status_code == 200, response.get_json()
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json()["items"] == [
        {
            "text": "The ferry sails at dawn.",
            "basis": "recollection",
            "confidence": 1.0,
        }
    ]
    assert response.get_json()["canonical_truth"] is False
    changed = player.patch(
        f"/api/v2/player/characters/{card['character_id']}",
        json={
            "authored_identity": {"initial_known_facts": ["NEW_SECRET passage under the marsh."]}
        },
    )
    assert changed.status_code == 200, changed.get_json()
    assert player.get(endpoint, query_string={"query": "NEW_SECRET"}).get_json()["items"] == []
    assert len(player.get(endpoint, query_string={"query": "ferry"}).get_json()["items"]) == 1
    assert player.get(endpoint, query_string={"limit": 21}).status_code == 400
    assert player.get(
        endpoint.replace(card["entity_id"], str(app.extensions["demo_ids"]["hero_id"]))
    ).status_code in {403, 404}
    return admin, player, card, endpoint, run


def test_character_knowledge_uses_pinned_starting_claims_and_preserves_scope(monkeypatch, tmp_path):
    check_pinned_knowledge(_app(monkeypatch, tmp_path))


def test_broad_scene_inspection_cannot_read_another_characters_learned_knowledge(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, endpoint, run = check_pinned_knowledge(app)
    ids, sim = app.extensions["demo_ids"], app.extensions["simulation"]
    spoken = player.post(
        "/api/v2/commands",
        json={
            "world_id": card["world_id"],
            "branch_id": str(ids["branch_id"]),
            "run_id": run,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.dialogue.speak",
            "parameters": {"text": "PRIVATE_RECOLLECTION brass gate."},
            "idempotency_key": "private-lore",
        },
    )
    assert spoken.status_code == 200, spoken.get_json()
    assert player.get(endpoint, query_string={"query": "PRIVATE_RECOLLECTION"}).get_json()["items"]
    sim.grant_authority(
        ids["world_id"], ids["actor_id"], roles=set(), capabilities={"world.read", "world.read.all"}
    )
    inspected = admin.get(endpoint, query_string={"query": "PRIVATE_RECOLLECTION"})
    assert inspected.status_code == 200 and inspected.get_json()["items"] == []
    context = admin.get(endpoint.removesuffix("knowledge") + "context").get_json()["situation"]
    assert (
        context["experiences"] == [] and context["memories"] == [] and context["identity"] is None
    )


def test_operator_and_god_body_do_not_share_omniscient_knowledge(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    ids = app.extensions["demo_ids"]
    world, branch, run, actor = (
        str(ids[key]) for key in ("world_id", "branch_id", "run_id", "actor_id")
    )
    body = admin.post(
        f"/api/v2/worlds/{world}/entities",
        json={
            "name": "River deity",
            "entity_type": "GOD",
            "controller_actor_id": actor,
            "public_state": {"x": 5, "y": 5, "hp": 100},
        },
    )
    assert body.status_code == 201, body.get_json()
    secret = admin.post(
        "/api/v2/commands",
        json={
            "world_id": world,
            "branch_id": branch,
            "run_id": run,
            "command_type": "tabletop.console.submit",
            "parameters": {"text": "OPERATOR_HIDDEN_ENDING"},
            "idempotency_key": "private-ending",
        },
    )
    assert secret.status_code == 200, secret.get_json()
    events = admin.get("/api/v2/events", query_string={"world_id": world, "branch_id": branch})
    assert "OPERATOR_HIDDEN_ENDING" in events.get_data(as_text=True)
    endpoint = f"/api/v2/worlds/{world}/branches/{branch}/entities/{body.get_json()['entity_id']}"
    context = admin.get(endpoint + "/context", query_string={"run_id": run})
    assert context.status_code == 200, context.get_json()
    assert "OPERATOR_HIDDEN_ENDING" not in context.get_data(as_text=True)
    assert (
        admin.get(
            endpoint + "/knowledge", query_string={"query": "OPERATOR_HIDDEN_ENDING"}
        ).get_json()["items"]
        == []
    )


def test_character_context_excludes_secrets(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]
    client = app.test_client()
    simulation = app.extensions["simulation"]
    record = simulation.entities[(ids["branch_id"], ids["hero_id"])]
    simulation.entities[(ids["branch_id"], ids["hero_id"])] = record.model_copy(
        update={
            "secret_state": {"true_identity": "HIDDEN_OPERATOR_TRUTH"},
        }
    )
    endpoint = (
        f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}"
        f"/entities/{ids['hero_id']}/context"
    )
    first = client.get(endpoint)
    assert first.status_code == 200
    assert "HIDDEN_OPERATOR_TRUTH" not in first.get_data(as_text=True)
    candidates = first.get_json()["action_candidates"]
    assert len(candidates) == 4
    assert {item["command_type"] for item in candidates} == {"tabletop.spatial.move"}
    assert first.get_json()["action_catalog_version"] == "tabletop-character-actions-1.3.0"
    assert first.get_json()["evidence_hash"] == client.get(endpoint).get_json()["evidence_hash"]
    assert client.get(endpoint.replace(str(ids["world_id"]), str(uuid.uuid4()))).status_code in {
        400,
        403,
        404,
    }
    other = next(
        entity.entity_id
        for entity in simulation.entities.values()
        if entity.branch_id == ids["branch_id"] and entity.entity_id != ids["hero_id"]
    )
    inspected = client.get(endpoint.replace(str(ids["hero_id"]), str(other)))
    assert inspected.status_code == 200
    assert inspected.get_json()["action_candidates"] == []


def test_candidate_attempt_does_not_reveal_hidden_obstacles_or_bypass_kernel(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]
    client = app.test_client()
    simulation = app.extensions["simulation"]
    state = simulation.states.get(ids["branch_id"])
    endpoint = (
        f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}"
        f"/entities/{ids['hero_id']}/context"
    )
    initial = client.get(endpoint).get_json()
    north = initial["action_candidates"][0]
    position = next(
        item for item in initial["situation"]["surroundings"] if item["reference"] == "self"
    )["position"]
    prior_obstacles = state.projections.get("tabletop.obstacles", {})
    state.projections["tabletop.obstacles"] = {
        "unknown-wall": {"x": position["x"], "y": position["y"] - 1}
    }
    blocked = client.get(endpoint).get_json()
    assert blocked["action_candidates"] == initial["action_candidates"]
    assert blocked["evidence_hash"] == initial["evidence_hash"]
    version = state.version
    count = len(simulation.events)
    payload = {
        "command_type": north["command_type"],
        "parameters": north["parameters"],
        "world_id": str(ids["world_id"]),
        "branch_id": str(ids["branch_id"]),
        "run_id": str(ids["run_id"]),
        "embodied_entity_id": str(ids["hero_id"]),
        "idempotency_key": "grounded-movement-attempt",
    }
    assert client.post("/api/v2/commands", json=payload).status_code == 400
    assert simulation.states.get(ids["branch_id"]).version == version
    assert len(simulation.events) == count
    state.projections["tabletop.obstacles"] = prior_obstacles
    accepted = client.post("/api/v2/commands", json=payload)
    assert accepted.status_code == 200
    repeated = client.post("/api/v2/commands", json=payload)
    assert repeated.status_code == 200
    assert repeated.get_json()["event"]["event_id"] == accepted.get_json()["event"]["event_id"]
    assert len(simulation.events) == count + 1


def test_blinded_context_keeps_self_and_prior_experience_but_hides_fresh_visual_facts(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]
    client = app.test_client()
    url = (
        f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}"
        f"/entities/{ids['hero_id']}/context"
    )
    sighted = client.get(url).get_json()["situation"]
    assert len(sighted["surroundings"]) > 1
    spoken = client.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.dialogue.speak",
            "world_id": str(ids["world_id"]),
            "branch_id": str(ids["branch_id"]),
            "run_id": str(ids["run_id"]),
            "embodied_entity_id": str(ids["hero_id"]),
            "seed": 2,
            "idempotency_key": "context-before-blind",
            "parameters": {"text": "I remember the market."},
        },
    )
    assert spoken.status_code == 200
    state = app.extensions["simulation"].states.get(ids["branch_id"])
    state.projections.setdefault("tabletop.sensory_profiles", {}).setdefault(
        str(ids["hero_id"]), {}
    )["blinded"] = True
    blind = client.get(url).get_json()["situation"]
    assert [item["reference"] for item in blind["surroundings"]] == ["self"]
    assert "I remember the market." in blind["experiences"]
    assert "I remember the market." in blind["memories"]
