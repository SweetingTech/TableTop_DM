from __future__ import annotations

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.integration


def test_accounts_roles_characters_and_games_survive_restart(
    integration_stack, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    app = create_app(artifact_root=tmp_path)

    with app.test_client() as administrator:
        signed_in = administrator.post(
            "/api/v2/auth/login", json={"username": "admin", "password": "admin123"}
        )
        assert signed_in.status_code == 200
        assert signed_in.get_json()["user"]["password_change_required"] is True
        blocked = administrator.get("/api/v2/worlds")
        assert blocked.status_code == 403
        changed = administrator.post(
            "/api/v2/auth/change-password",
            json={
                "current_password": "admin123",
                "new_password": "Durable-Administrator-2026!",
            },
        )
        assert changed.status_code == 200
        world_id = administrator.get("/api/v2/worlds").get_json()[0]["world_id"]
        created = administrator.post(
            "/api/v2/admin/users",
            json={
                "username": "adventurer",
                "temporary_password": "Temporary-Adventurer-2026!",
                "profile": {
                    "display_name": "Alex Rivers",
                    "pronouns": "they/them",
                    "timezone": "America/New_York",
                    "locale": "en-US",
                },
            },
        )
        assert created.status_code == 201
        user_id = created.get_json()["user"]["user_id"]
        roles = administrator.put(
            f"/api/v2/admin/users/{user_id}/worlds/{world_id}/roles",
            json={"roles": ["DM", "PLAYER"]},
        )
        assert set(roles.get_json()["user"]["world_roles"][0]["roles"]) == {"DM", "PLAYER"}

    with app.test_client() as adventurer:
        assert (
            adventurer.post(
                "/api/v2/auth/login",
                json={"username": "adventurer", "password": "Temporary-Adventurer-2026!"},
            ).status_code
            == 200
        )
        assert (
            adventurer.post(
                "/api/v2/auth/change-password",
                json={
                    "current_password": "Temporary-Adventurer-2026!",
                    "new_password": "Durable-Adventurer-2026!",
                },
            ).status_code
            == 200
        )
        character = adventurer.post(
            "/api/v2/player/characters",
            json={
                "world_id": world_id,
                "creation_method": "GENERATED",
                "seed": 2026,
                "name": "Vesper Vale",
                "authored_identity": {
                    "backstory": "Raised among the lantern keepers.",
                    "motives": ["Find the missing keeper"],
                    "values": ["Mercy"],
                    "bonds": ["The harbor watch"],
                    "secrets": ["I hid the spare key."],
                    "initial_known_facts": ["The ferry sails at dawn."],
                },
            },
        )
        assert character.status_code == 201
        assert character.get_json()["status"] == "ALIVE"
        identity = character.get_json()["authored_identity"]
        version = character.get_json()["card_version"]
        assert len(version) == 64
        rejected = adventurer.patch(
            f"/api/v2/player/characters/{character.get_json()['character_id']}",
            json={"authored_identity": {"secrets": ["private" * 100]}},
        )
        assert rejected.status_code == 400
        assert "privateprivate" not in rejected.get_data(as_text=True)
        game = adventurer.post(
            "/api/v2/dm/games",
            json={"world_id": world_id, "name": "The Lantern Vault", "max_players": 5},
        )
        assert game.status_code == 201
        game_id = game.get_json()["game_id"]
        assignable = adventurer.get(f"/api/v2/dm/games/{game_id}/users/{user_id}/characters")
        assert assignable.status_code == 200
        summaries = assignable.get_json()["items"]
        assert summaries == [
            {
                "character_id": character.get_json()["character_id"],
                "name": "Vesper Vale",
                "class_name": character.get_json()["class_name"],
                "level": 1,
                "status": "ALIVE",
            }
        ]
        assigned = adventurer.put(
            f"/api/v2/dm/games/{game_id}/members",
            json={
                "user_id": user_id,
                "character_id": summaries[0]["character_id"],
                "membership_role": "PLAYER",
                "status": "READY",
            },
        )
        assert assigned.status_code == 200, assigned.get_json()
        assert assigned.get_json()["members"][0]["character_name"] == "Vesper Vale"

    restarted = create_app(artifact_root=tmp_path)
    with restarted.test_client() as client:
        assert (
            client.post(
                "/api/v2/auth/login",
                json={"username": "adventurer", "password": "Durable-Adventurer-2026!"},
            ).status_code
            == 200
        )
        characters = client.get("/api/v2/player/characters").get_json()["items"]
        games = client.get("/api/v2/games").get_json()["items"]
        assert characters[0]["name"] == "Vesper Vale"
        assert characters[0]["authored_identity"] == identity
        assert characters[0]["card_version"] == version
        assert "_authored_identity_v1" not in characters[0]["sheet"]
        assert games[0]["game_id"] == game_id
        assert games[0]["members"][0]["character_id"] == characters[0]["character_id"]
        assert (
            client.get(f"/api/v2/dm/games/{game_id}/users/{user_id}/characters").get_json()[
                "items"
            ][0]["name"]
            == "Vesper Vale"
        )
