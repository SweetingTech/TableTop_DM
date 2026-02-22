import pytest

from app import app

pytestmark = pytest.mark.unit


class Principal:
    def __init__(self, role: str):
        self.role = role

    def is_gm(self) -> bool:
        return self.role == "GM"


def test_campaign_session_load_for_gm(monkeypatch):
    monkeypatch.setattr(
        "shared.auth.principal.load_principal", lambda *_args, **_kwargs: Principal("GM")
    )

    def fake_execute_one(_query, _params):
        return {
            "encounter_id": "55555555-5555-5555-5555-555555555551",
            "session_id": "66666666-6666-6666-6666-666666666661",
            "status": "ACTIVE",
            "round_number": 1,
        }

    monkeypatch.setattr("shared.db.connection.execute_one", fake_execute_one)

    with app.test_client() as client:
        response = client.get(
            "/api/campaigns/11111111-1111-1111-1111-111111111111/session",
            query_string={"principal_id": "22222222-2222-2222-2222-222222222221"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["session_id"] == "66666666-6666-6666-6666-666666666661"


def test_campaign_session_load_for_non_gm_forbidden(monkeypatch):
    monkeypatch.setattr(
        "shared.auth.principal.load_principal", lambda *_args, **_kwargs: Principal("PLAYER")
    )

    with app.test_client() as client:
        response = client.get(
            "/api/campaigns/11111111-1111-1111-1111-111111111111/session",
            query_string={"principal_id": "22222222-2222-2222-2222-222222222222"},
        )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Only GM can load session"
