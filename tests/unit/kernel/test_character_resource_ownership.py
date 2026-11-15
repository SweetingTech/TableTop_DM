from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "DEAD"),
        ("current_hit_points", 1),
        ("maximum_hit_points", 50),
        ("armor_class", 25),
        ("speed", 90),
        ("world_id", str(uuid.uuid4())),
    ],
)
def test_bound_card_cannot_change_physical_resources_or_world(monkeypatch, tmp_path, field, value):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    endpoint = f"/api/v2/player/characters/{card['character_id']}"
    sim = app.extensions["simulation"]
    state = sim.states.get(uuid.UUID(base["branch_id"]))
    before = state.state_hash, state.version, len(sim.events)
    for client in (player, admin):
        response = client.patch(endpoint, json={field: value, "name": "Must not partially save"})
        assert response.status_code == 400, response.get_json()
        saved = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert saved == card
        assert (state.state_hash, state.version, len(sim.events)) == before


def test_bound_identity_edits_remain_available_and_unbound_progress_can_be_authored(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    endpoint = f"/api/v2/player/characters/{card['character_id']}"
    edited = player.patch(
        endpoint,
        json={
            "world_id": base["world_id"],
            "authored_identity": {"backstory": "A revised authored origin."},
        },
    )
    assert edited.status_code == 200, edited.get_json()
    assert edited.get_json()["authored_identity"]["backstory"] == "A revised authored origin."
    assert edited.get_json()["current_hit_points"] == card["current_hit_points"]
    created = player.post("/api/v2/player/characters", json={"name": "Unbound"})
    assert created.status_code == 201
    unbound = player.patch(
        f"/api/v2/player/characters/{created.get_json()['character_id']}",
        json={
            "current_hit_points": 4,
            "status": "MISSING",
        },
    )
    assert unbound.status_code == 200 and unbound.get_json()["current_hit_points"] == 4


def test_explicit_null_patch_does_not_detach_bound_body(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    result = player.patch(
        f"/api/v2/player/characters/{card['character_id']}", json={"world_id": None}
    )
    assert result.status_code == 200
    assert result.get_json()["world_id"] == card["world_id"]
    assert result.get_json()["entity_id"] == card["entity_id"]
