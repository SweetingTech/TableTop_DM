from __future__ import annotations

import uuid

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit


def _setup(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]
    path = (
        f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}"
        f"/entities/{ids['hero_id']}/scene"
    )
    return app, ids, app.test_client(), path


def _speak(client, ids, key="refresh-dialogue"):
    response = client.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.dialogue.speak",
            "world_id": str(ids["world_id"]),
            "branch_id": str(ids["branch_id"]),
            "run_id": str(ids["run_id"]),
            "embodied_entity_id": str(ids["hero_id"]),
            "parameters": {"text": "The tide is rising."},
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200
    return response.get_json()


def test_scene_refresh_waits_for_observation_without_reexecuting_command(monkeypatch, tmp_path):
    app, ids, client, path = _setup(monkeypatch, tmp_path)
    simulation = app.extensions["simulation"]
    original = simulation.subjective_projector
    pending = []
    simulation.configure_subjective_projector(pending.append)
    receipt = _speak(client, ids)
    cursor = receipt["scene_refresh"]
    assert cursor == {
        "world_id": str(ids["world_id"]),
        "branch_id": str(ids["branch_id"]),
        "observer_entity_id": str(ids["hero_id"]),
        "event_id": receipt["event"]["event_id"],
        "projection_version": simulation.states.get(ids["branch_id"]).version,
    }
    waiting = client.get(path, query_string={"after_event_id": cursor["event_id"]})
    assert waiting.status_code == 200
    assert waiting.headers["Cache-Control"] == "no-store"
    assert waiting.get_json()["refresh"] == {
        "event_id": cursor["event_id"],
        "ready": False,
        "observed": False,
    }
    assert waiting.get_json()["projection_version"] == cursor["projection_version"]
    assert original is not None
    original(pending[0])
    ready = client.get(path, query_string={"after_event_id": cursor["event_id"]}).get_json()
    assert ready["refresh"] == {"event_id": cursor["event_id"], "ready": True, "observed": True}
    matching = [
        row for row in ready["recent_observations"] if row["source_event_id"] == cursor["event_id"]
    ]
    assert len(matching) == 1
    assert matching[0]["observation_id"] != cursor["event_id"]
    assert matching[0]["summary"] == "The tide is rising."
    retry = _speak(client, ids)
    assert retry["event"]["event_id"] == cursor["event_id"]
    assert retry["scene_refresh"]["projection_version"] == cursor["projection_version"]


def test_scene_refresh_rejects_foreign_viewpoint_and_unknown_receipts(monkeypatch, tmp_path):
    app, ids, client, path = _setup(monkeypatch, tmp_path)
    receipt = _speak(client, ids)
    event = receipt["event"]["event_id"]
    assert client.get(path, query_string={"after_event_id": "invalid"}).status_code == 400
    assert client.get(path, query_string={"after_event_id": str(uuid.uuid4())}).status_code == 404
    other_id = next(
        entity.entity_id
        for entity in app.extensions["simulation"].entities.values()
        if entity.branch_id == ids["branch_id"] and entity.entity_id != ids["hero_id"]
    )
    other = path.replace(str(ids["hero_id"]), str(other_id))
    assert client.get(other, query_string={"after_event_id": event}).status_code == 403
    assert "refresh" not in client.get(path).get_json()


def test_unperceived_action_refresh_completes_without_inventing_experience(monkeypatch, tmp_path):
    app, ids, client, path = _setup(monkeypatch, tmp_path)
    state = app.extensions["simulation"].states.get(ids["branch_id"])
    profile = state.projections["tabletop.sensory_profiles"][str(ids["hero_id"])]
    profile.update({"blinded": True, "deafened": True, "sight_acuity": 0, "hearing_acuity": 0})
    receipt = _speak(client, ids)
    event = receipt["event"]["event_id"]
    scene = client.get(path, query_string={"after_event_id": event}).get_json()
    assert scene["refresh"] == {"event_id": event, "ready": True, "observed": False}
    assert not any(row["source_event_id"] == event for row in scene["recent_observations"])
