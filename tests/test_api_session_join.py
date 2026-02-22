from app import app


def test_player_can_join_session(monkeypatch):
    responses = iter(
        [
            {"campaign_id": "11111111-1111-1111-1111-111111111111"},
            {"role": "PLAYER"},
        ]
    )

    def fake_execute_one(_query, _params):
        return next(responses)

    monkeypatch.setattr("shared.db.connection.execute_one", fake_execute_one)

    with app.test_client() as client:
        response = client.post(
            "/api/sessions/66666666-6666-6666-6666-666666666661/join",
            json={"principal_id": "22222222-2222-2222-2222-222222222222"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["joined"] is True
    assert payload["role"] == "PLAYER"
    assert payload["session_id"] == "66666666-6666-6666-6666-666666666661"


def test_non_member_cannot_join_session(monkeypatch):
    responses = iter([
        {"campaign_id": "11111111-1111-1111-1111-111111111111"},
        None,
    ])

    def fake_execute_one(_query, _params):
        return next(responses)

    monkeypatch.setattr("shared.db.connection.execute_one", fake_execute_one)

    with app.test_client() as client:
        response = client.post(
            "/api/sessions/66666666-6666-6666-6666-666666666661/join",
            json={"principal_id": "99999999-9999-9999-9999-999999999999"},
        )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Principal is not a campaign member"
