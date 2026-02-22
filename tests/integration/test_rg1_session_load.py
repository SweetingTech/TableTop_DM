import pytest

from app import app

pytestmark = pytest.mark.integration

CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
DM_PRINCIPAL_ID = "22222222-2222-2222-2222-222222222221"
PLAYER_PRINCIPAL_ID = "22222222-2222-2222-2222-222222222222"
EXPECTED_SESSION_ID = "66666666-6666-6666-6666-666666666661"


def test_dm_can_load_seeded_campaign_and_session(integration_stack) -> None:
    del integration_stack

    with app.test_client() as client:
        campaign_resp = client.get("/api/campaigns")
        assert campaign_resp.status_code == 200
        campaigns = campaign_resp.get_json()
        assert any(c["id"] == CAMPAIGN_ID for c in campaigns)

        session_resp = client.get(
            f"/api/campaigns/{CAMPAIGN_ID}/session",
            query_string={"principal_id": DM_PRINCIPAL_ID},
        )
        assert session_resp.status_code == 200
        payload = session_resp.get_json()
        assert payload["campaign_id"] == CAMPAIGN_ID
        assert payload["session_id"] == EXPECTED_SESSION_ID
        assert payload["encounter_id"] == "55555555-5555-5555-5555-555555555551"


def test_non_gm_cannot_load_campaign_session(integration_stack) -> None:
    del integration_stack

    with app.test_client() as client:
        session_resp = client.get(
            f"/api/campaigns/{CAMPAIGN_ID}/session",
            query_string={"principal_id": PLAYER_PRINCIPAL_ID},
        )
        assert session_resp.status_code == 403
        assert session_resp.get_json()["error"] == "Only GM can load session"
