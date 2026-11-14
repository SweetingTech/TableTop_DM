from __future__ import annotations

import uuid

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit


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
    assert first.get_json()["action_catalog_version"] == "tabletop-character-actions-1.2.0"
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
