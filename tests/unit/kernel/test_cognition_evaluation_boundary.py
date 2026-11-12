from __future__ import annotations

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit


def test_character_rejects_caller_authored_decisions(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    app = create_app(artifact_root=tmp_path)
    ids = app.extensions["demo_ids"]
    client = app.test_client()
    persona = client.post(
        "/api/v2/personas/generate", json={"seed": 7, "purpose": "CHARACTER"}
    ).get_json()
    denied = client.post(
        "/api/v2/cognition/decide",
        json={
            "persona_id": persona["persona_id"],
            "seed": 1,
            "embodied_entity_id": str(ids["hero_id"]),
            "situation": {"secret": "HIDDEN_OPERATOR_TRUTH"},
            "actions": [
                {
                    "action": "talk",
                    "command_type": "tabletop.console.submit",
                    "parameters": {"text": "hidden"},
                }
            ],
        },
    )
    assert denied.status_code == 403
    assert (
        app.extensions["minds"].inspect(ids["hero_id"], branch_id=ids["branch_id"])["decisions"]
        == []
    )


def test_player_cannot_submit_caller_authored_evaluation_context(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", "context-test-only-token")
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    assert (
        admin.post(
            "/api/v2/auth/login", json={"username": "admin", "password": "admin123"}
        ).status_code
        == 200
    )
    assert (
        admin.post(
            "/api/v2/auth/change-password",
            json={"current_password": "admin123", "new_password": "Context-Administrator-1"},
        ).status_code
        == 200
    )
    created = admin.post(
        "/api/v2/admin/users",
        json={
            "username": "contextplayer",
            "temporary_password": "Context-Temporary-1",
            "profile": {"display_name": "Context Player"},
        },
    ).get_json()
    world = app.extensions["demo_ids"]["world_id"]
    assert (
        admin.put(
            f"/api/v2/admin/users/{created['user']['user_id']}/worlds/{world}/roles",
            json={"roles": ["PLAYER"]},
        ).status_code
        == 200
    )
    player = app.test_client()
    assert (
        player.post(
            "/api/v2/auth/login",
            json={"username": "contextplayer", "password": "Context-Temporary-1"},
        ).status_code
        == 200
    )
    assert (
        player.post(
            "/api/v2/auth/change-password",
            json={
                "current_password": "Context-Temporary-1",
                "new_password": "Context-Player-Final-1",
            },
        ).status_code
        == 200
    )
    response = player.post(
        "/api/v2/cognition/decide", json={"situation": {"secret": "PRIVATE_PLOT"}}
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "permission_denied"
