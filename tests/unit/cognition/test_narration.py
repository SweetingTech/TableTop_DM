from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene

pytestmark = pytest.mark.unit


def exercise_narration(app, admin, player, card, run, speaker, base):
    route = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/narration"

    def submit(command, parameters, key, entity_id=speaker):
        response = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": entity_id,
                "command_type": command,
                "parameters": parameters,
                "idempotency_key": key,
            },
        )
        assert response.status_code == 200, response.get_json()
        return response.get_json()["event"]["event_id"]

    visible = submit("tabletop.spatial.move", {"dx": 0, "dy": 1}, "narrated-move")
    audible = submit(
        "tabletop.dialogue.speak",
        {"text": "The ferry is delayed.", "language": "common", "volume": "NORMAL"},
        "narrated-testimony",
    )
    distant = admin.post(
        f"/api/v2/worlds/{base['world_id']}/entities",
        json={
            **{key: base[key] for key in ("world_id", "branch_id")},
            "name": "Distant messenger",
            "entity_type": "NPC",
            "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
            "public_state": {"x": 80, "y": 80},
            "secret_state": {"private_note": "Never put this in prose"},
        },
    )
    assert distant.status_code == 201, distant.get_json()
    hidden = submit(
        "tabletop.dialogue.speak",
        {"text": "Meet at the old mill."},
        "unwitnessed-testimony",
        distant.get_json()["entity_id"],
    )
    operator_request = {"run_id": run, "audience": "OPERATOR"}
    character_request = {
        "run_id": run,
        "audience": "CHARACTER",
        "observer_entity_id": card["entity_id"],
    }

    def render(client, options):
        response = client.post(route, json=options)
        assert response.status_code == 200, response.get_json()
        assert response.headers["Cache-Control"] == "no-store"
        return response.get_json()

    operator = render(admin, operator_request)["entries"]
    character = render(player, character_request)["entries"]
    spectator = render(player, {**character_request, "audience": "SPECTATOR"})["entries"]
    assert [entry["source_event_id"] for entry in operator] == [visible, audible, hidden]
    assert [entry["source_event_id"] for entry in character] == [visible, audible]
    assert [entry["source_event_id"] for entry in spectator] == [visible]
    assert operator[-1]["text"] == "A voice says “Meet at the old mill.”"
    assert operator[-1]["source_observation_id"] is None
    assert character[-1]["text"] == "You hear “The ferry is delayed.”"
    assert character[-1]["source_observation_id"]
    assert spectator[0]["text"] == "Someone moves to (1, 1)."
    assert "Never put this in prose" not in str(operator)
    assert render(player, character_request)["entries"] == character
    assert render(player, {**character_request, "after_event_id": visible}) == {
        "entries": [character[-1]],
        "next_after_event_id": audible,
    }
    assert (
        player.post(route, json={**character_request, "after_event_id": hidden}).status_code == 404
    )
    assert player.post(route, json=operator_request).status_code == 403
    assert (
        player.post(route, json={**character_request, "observer_entity_id": speaker}).status_code
        == 403
    )
    assert (
        player.post(route, json={**character_request, "run_id": str(uuid.uuid4())}).status_code
        == 400
    )
    assert player.get(route + "/" + operator[0]["narration_id"]).status_code == 404
    assert admin.get(route + "/" + character[0]["narration_id"]).status_code == 404
    return route, character


def test_narration_routes_use_frozen_evidence_and_private_audiences(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, run, speaker, base = setup_scene(app)
    route, entries = exercise_narration(app, admin, player, card, run, speaker, base)
    saved = player.get(route + "/" + entries[0]["narration_id"])
    assert saved.status_code == 200 and saved.get_json() == entries[0]
    assert saved.headers["Cache-Control"] == "no-store"
