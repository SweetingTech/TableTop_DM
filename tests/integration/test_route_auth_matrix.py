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
