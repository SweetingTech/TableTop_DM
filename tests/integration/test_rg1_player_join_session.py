import pytest

from app import app

pytestmark = pytest.mark.integration

SESSION_ID = "66666666-6666-6666-6666-666666666661"
PLAYER_PRINCIPAL_ID = "22222222-2222-2222-2222-222222222222"


def test_player_can_join_seeded_session(integration_stack) -> None:
    del integration_stack

    with app.test_client() as client:
        response = client.post(
            f"/api/sessions/{SESSION_ID}/join",
            json={"principal_id": PLAYER_PRINCIPAL_ID},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["joined"] is True
    assert payload["session_id"] == SESSION_ID
    assert payload["role"] == "PLAYER"
