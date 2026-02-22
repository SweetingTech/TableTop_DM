import pytest

from app import app

pytestmark = pytest.mark.unit


class Principal:
    def __init__(self, role: str):
        self.role = role


def test_player_can_join_session(monkeypatch):
    monkeypatch.setattr(
        "shared.auth.principal.load_principal",
        lambda *_args, **_kwargs: Principal("PLAYER"),
    )
    monkeypatch.setattr(
        "shared.db.connection.execute_one",
        lambda *_args, **_kwargs: {"campaign_id": "11111111-1111-1111-1111-111111111111"},
    )

    with app.test_client() as client:
        response = client.post(
            "/api/sessions/66666666-6666-6666-6666-666666666661/join",
            json={"principal_id": "22222222-2222-2222-2222-222222222222"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["joined"] is True
    assert payload["role"] == "PLAYER"


def test_non_member_cannot_join_session(monkeypatch):
    monkeypatch.setattr(
        "shared.auth.principal.load_principal", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        "shared.db.connection.execute_one",
        lambda *_args, **_kwargs: {"campaign_id": "11111111-1111-1111-1111-111111111111"},
    )

    with app.test_client() as client:
        response = client.post(
            "/api/sessions/66666666-6666-6666-6666-666666666661/join",
            json={"principal_id": "99999999-9999-9999-9999-999999999999"},
        )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Principal is not a campaign member"
