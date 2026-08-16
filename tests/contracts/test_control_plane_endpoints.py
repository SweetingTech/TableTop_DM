import pytest
from pathlib import Path

from app import app

pytestmark = pytest.mark.contracts


def test_campaign_crud_contract(monkeypatch):
    monkeypatch.setattr(
        "shared.db.connection.execute_one",
        lambda *_args, **_kwargs: {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "New Campaign",
            "slug": "new-campaign",
            "status": "ACTIVE",
            "mode": "EXPLORATION",
        },
    )
    with app.test_client() as client:
        r = client.post(
            "/api/campaigns",
            json={
                "name": "New Campaign",
                "slug": "new-campaign",
                "status": "ACTIVE",
                "mode": "EXPLORATION",
            },
        )
    assert r.status_code == 201
    assert r.get_json()["slug"] == "new-campaign"


def test_entity_control_validation():
    with app.test_client() as client:
        r = client.post(
            "/api/entities/11111111-1111-1111-1111-111111111111/control",
            json={"controlled_by": "BOT"},
        )
    assert r.status_code == 400


def test_ai_test_provider_mock():
    with app.test_client() as client:
        r = client.post(
            "/api/ai/test_provider", json={"provider": "mock", "model": "mock-model"}
        )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_control_plane_reuses_real_tokens_and_matches_smoke_token_roles():
    control_js = Path("static/js/control/legacy-control.js").read_text(encoding="utf-8")

    assert "ttdm_control_principal_id:${campaignId}" in control_js
    assert "ttdm_join_token:${campaignId}:${principalId}" in control_js
    assert "explicitJoinToken || storedJoinToken" in control_js
    assert "member.role === 'GM' ? 'dm' : 'player'" in control_js
