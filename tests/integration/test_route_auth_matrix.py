from __future__ import annotations

from pathlib import Path

import pytest

from app import app

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"
NPC_ID = "33333333-3333-3333-3333-333333333333"
NON_MEMBER_ID = "99999999-9999-4999-8999-999999999999"
DM_ID = "22222222-2222-2222-2222-222222222221"
PLAYER_ID = "22222222-2222-2222-2222-222222222222"
ENCOUNTER_ID = "55555555-5555-5555-5555-555555555551"


def test_route_auth_matrix_document_has_release_gate_columns():
    matrix = (ROOT / "docs" / "release" / "1.0-route-auth-matrix.md").read_text(encoding="utf-8")
    for column in (
        "Anonymous",
        "GM",
        "Player",
        "Campaign membership",
        "Session membership",
        "Principal scoped",
        "Visibility filtered",
        "DM-only risk",
        "Test coverage",
    ):
        assert column in matrix
    for family in ("Player state", "Realtime join", "Continuity/recaps", "Save/load", "Global/API settings"):
        assert family in matrix


def test_principal_scoped_routes_reject_anonymous_and_non_member(integration_stack):
    del integration_stack
    with app.test_client() as client:
        anonymous_state = client.get(f"/api/sessions/{SESSION_ID}/player_state")
        assert anonymous_state.status_code == 401

        non_member_state = client.get(
            f"/api/sessions/{SESSION_ID}/player_state",
            query_string={"principal_id": NON_MEMBER_ID},
        )
        assert non_member_state.status_code == 403

        anonymous_memory = client.get(f"/api/campaigns/{CAMPAIGN_ID}/npc_memory/{NPC_ID}")
        assert anonymous_memory.status_code == 401

        non_member_join = client.post(
            f"/api/sessions/{SESSION_ID}/join",
            json={"principal_id": NON_MEMBER_ID},
        )
        assert non_member_join.status_code == 403


def test_dm_only_game_routes_reject_anonymous_and_players(integration_stack):
    del integration_stack
    with app.test_client() as client:
        anonymous_encounter = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/encounters",
            json={"session_id": SESSION_ID},
        )
        player_encounter = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/encounters",
            query_string={"principal_id": PLAYER_ID, "join_token": f"player-smoke-join-{PLAYER_ID}"},
            json={"session_id": SESSION_ID},
        )
        anonymous_advance = client.post(f"/api/encounters/{ENCOUNTER_ID}/advance")
        player_advance = client.post(
            f"/api/encounters/{ENCOUNTER_ID}/advance",
            query_string={"principal_id": PLAYER_ID, "join_token": f"player-smoke-join-{PLAYER_ID}"},
        )
        anonymous_narrate = client.post("/api/narrate", json={"campaign_id": CAMPAIGN_ID})
        player_narrate = client.post(
            "/api/narrate",
            query_string={"principal_id": PLAYER_ID, "join_token": f"player-smoke-join-{PLAYER_ID}"},
            json={"campaign_id": CAMPAIGN_ID},
        )

    assert anonymous_encounter.status_code == 401
    assert player_encounter.status_code == 403
    assert anonymous_advance.status_code == 401
    assert player_advance.status_code == 403
    assert anonymous_narrate.status_code == 401
    assert player_narrate.status_code == 403


def test_gm_can_use_dm_only_game_routes_with_valid_local_identity(integration_stack, monkeypatch):
    del integration_stack

    class DummyStateMachine:
        def advance_turn(self, _encounter_id):
            return {"current_turn_order": 2}

    class DummyNarrator:
        def __init__(self, **_kwargs):
            pass

        def narrate_event(self, **_kwargs):
            return "The scene continues."

    monkeypatch.setattr("services.orchestrator.state_machine.StateMachine", DummyStateMachine)
    monkeypatch.setattr("services.llm.adapter.DMNarrationAgent", DummyNarrator)
    gm_query = {"principal_id": DM_ID, "join_token": f"dm-smoke-join-{DM_ID}"}

    with app.test_client() as client:
        encounter = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/encounters",
            query_string=gm_query,
            json={"session_id": SESSION_ID},
        )
        advance = client.post(f"/api/encounters/{ENCOUNTER_ID}/advance", query_string=gm_query)
        narrate = client.post(
            "/api/narrate",
            query_string=gm_query,
            json={"campaign_id": CAMPAIGN_ID, "event_data": {}, "context": "qa"},
        )

    assert encounter.status_code == 200
    assert advance.status_code == 200
    assert advance.get_json()["current_turn_order"] == 2
    assert narrate.status_code == 200
    assert narrate.get_json()["narration"] == "The scene continues."
