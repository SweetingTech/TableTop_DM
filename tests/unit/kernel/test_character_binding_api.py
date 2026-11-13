from __future__ import annotations

import os
import secrets
import uuid

import pytest

from cognition.models import RuntimeAssignment
from kernel.api.app import create_app

pytestmark = pytest.mark.unit


def setup_bound_character(app, token=None, *, scope=None):
    token = token or os.environ.get("TTDM_OPERATOR_TOKEN")
    admin = app.test_client()
    if token:
        admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = token
    world = str(scope["world_id"] if scope else app.extensions["demo_ids"]["world_id"])
    name = "card" + uuid.uuid4().hex[:12]
    temporary = secrets.token_urlsafe(24)
    created = admin.post(
        "/api/v2/admin/users",
        json={
            "username": name,
            "temporary_password": temporary,
            "profile": {"display_name": "History Player"},
        },
    )
    assert created.status_code == 201
    user = created.get_json()["user"]["user_id"]
    assert (
        admin.put(
            f"/api/v2/admin/users/{user}/worlds/{world}/roles", json={"roles": ["PLAYER"]}
        ).status_code
        == 200
    )
    player = app.test_client()
    assert (
        player.post(
            "/api/v2/auth/login", json={"username": name, "password": temporary}
        ).status_code
        == 200
    )
    assert (
        player.post(
            "/api/v2/auth/change-password",
            json={"current_password": temporary, "new_password": secrets.token_urlsafe(24)},
        ).status_code
        == 200
    )
    response = player.post(
        "/api/v2/player/characters",
        json={
            "world_id": world,
            "name": "Nyra History",
            "authored_identity": {
                "backstory": "Raised by sailors.",
                "motives": ["Protect the crew."],
                "secrets": ["SELF_PRIVATE_MAP"],
                "initial_known_facts": ["The ferry sails at dawn."],
            },
        },
    )
    assert response.status_code == 201
    card = response.get_json()
    game = admin.post(
        "/api/v2/dm/games", json={"world_id": world, "name": "History binding game"}
    ).get_json()
    response = admin.put(
        f"/api/v2/dm/games/{game['game_id']}/members",
        json={"user_id": user, "membership_role": "PLAYER", "character_id": card["character_id"]},
    )
    assert response.status_code == 200
    card = next(
        c
        for c in player.get("/api/v2/player/characters").get_json()["items"]
        if c["character_id"] == card["character_id"]
    )
    ids = (
        {"branch_id": scope["canonical_branch_id"], "run_id": scope["current_run_id"]}
        if scope
        else app.extensions["demo_ids"]
    )
    path = f"/api/v2/worlds/{world}/branches/{ids['branch_id']}/entities/{card['entity_id']}"
    run = str(ids["run_id"])
    return admin, player, card, game, path, run, user


def _app(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    return create_app(artifact_root=tmp_path)


def test_initial_binding_pins_history_and_explicit_successor_preserves_mind(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, path, run, user = setup_bound_character(app)
    history_path = f"/api/v2/player/characters/{card['character_id']}/history"
    history = player.get(history_path).get_json()["items"]
    assert len(history) == 1 and history[0]["card_version"] == card["card_version"]
    binding = player.get(path + "/character-binding", query_string={"run_id": run}).get_json()[
        "binding"
    ]
    assert binding["purpose"] == "CHARACTER"
    assert binding["card_revision_id"] == history[0]["revision_id"]
    assert binding["entity_id"] != binding["persona_id"]
    ids = app.extensions["demo_ids"]
    assignment = RuntimeAssignment(
        world_id=ids["world_id"],
        branch_id=ids["branch_id"],
        run_id=ids["run_id"],
        entity_id=uuid.UUID(card["entity_id"]),
        runtime_kind="HUMAN",
        runtime_config={"seat": "PRIVATE_CONTROLLER_METADATA"},
    )
    app.extensions["minds"].set_runtime_assignment(assignment)
    assert (
        player.post(
            "/api/v2/commands",
            json={
                "command_type": "tabletop.dialogue.speak",
                "world_id": card["world_id"],
                "branch_id": str(ids["branch_id"]),
                "run_id": run,
                "embodied_entity_id": card["entity_id"],
                "parameters": {"text": "I promised to protect the crew."},
                "idempotency_key": "history-before-rebind",
            },
        ).status_code
        == 200
    )
    context = player.get(path + "/context").get_json()
    assert context["situation"]["identity"]["backstory"] == "Raised by sailors."
    assert "SELF_PRIVATE_MAP" in context["situation"]["identity"]["secrets"]
    assert "The ferry sails at dawn." not in context["situation"]["experiences"]
    assert context["situation"]["identity"]["starting_knowledge_claims"] == [
        "The ferry sails at dawn."
    ]
    before_mind = app.extensions["minds"].inspect(
        uuid.UUID(card["entity_id"]), branch_id=app.extensions["demo_ids"]["branch_id"]
    )
    assert (
        app.extensions["minds"]
        .get(uuid.UUID(card["entity_id"]), branch_id=ids["branch_id"])
        .memories
    )
    assert (
        player.patch(
            f"/api/v2/player/characters/{card['character_id']}",
            json={"authored_identity": {"backstory": "I now serve the mountain village."}},
        ).status_code
        == 200
    )
    updated = player.get(history_path).get_json()["items"]
    assert len(updated) == 2 and updated[0] == history[0]
    assert player.get(path + "/context").get_json()["evidence_hash"] == context["evidence_hash"]
    # Retrying the roster must not silently adopt a later card.
    assert (
        admin.put(
            f"/api/v2/dm/games/{game['game_id']}/members",
            json={
                "user_id": user,
                "membership_role": "PLAYER",
                "character_id": card["character_id"],
            },
        ).status_code
        == 200
    )
    assert (
        player.get(path + "/character-binding", query_string={"run_id": run}).get_json()["binding"]
        == binding
    )
    payload = {
        "character_id": card["character_id"],
        "run_id": run,
        "card_revision_id": updated[-1]["revision_id"],
        "replaces_binding_id": binding["binding_id"],
    }
    result = player.post(path + "/character-binding", json=payload)
    assert result.status_code == 200
    successor = result.get_json()
    assert successor["binding_id"] != binding["binding_id"]
    assert player.post(path + "/character-binding", json=payload).get_json() == successor
    assert (
        player.get(path + "/context").get_json()["situation"]["identity"]["backstory"]
        == "I now serve the mountain village."
    )
    assert (
        app.extensions["minds"].inspect(
            uuid.UUID(card["entity_id"]), branch_id=app.extensions["demo_ids"]["branch_id"]
        )
        == before_mind
    )
    assert (
        app.extensions["minds"].runtime_assignment(
            world_id=ids["world_id"],
            branch_id=ids["branch_id"],
            run_id=ids["run_id"],
            entity_id=uuid.UUID(card["entity_id"]),
        )
        == assignment
    )
    assert "PRIVATE_CONTROLLER_METADATA" not in str(
        player.get(path + "/context").get_json()["situation"]
    )
    payload["card_revision_id"] = history[0]["revision_id"]
    assert player.post(path + "/character-binding", json=payload).status_code == 400
    assert player.delete(f"/api/v2/player/characters/{card['character_id']}").status_code == 400


def test_foreign_card_body_run_and_playtester_cannot_be_bound(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app)
    initial = player.get(path + "/context").get_json()
    revisions = player.get(f"/api/v2/player/characters/{card['character_id']}/history").get_json()[
        "items"
    ]
    payload = {
        "character_id": card["character_id"],
        "run_id": run,
        "card_revision_id": revisions[0]["revision_id"],
        "replaces_binding_id": initial["binding"]["binding_id"],
    }
    evaluation = admin.post("/api/v2/personas/generate", json={"seed": 774}).get_json()
    payload["persona_version_id"] = admin.post(
        f"/api/v2/personas/{evaluation['persona_id']}/compile"
    ).get_json()["persona_version"]
    assert player.post(path + "/character-binding", json=payload).status_code == 400
    payload.pop("persona_version_id")
    original_run = payload["run_id"]
    payload["run_id"] = str(uuid.uuid4())
    assert player.post(path + "/character-binding", json=payload).status_code == 400
    payload["run_id"] = original_run
    payload["card_revision_id"] = str(uuid.uuid4())
    assert player.post(path + "/character-binding", json=payload).status_code == 400
    foreign = path.replace(card["entity_id"], str(app.extensions["demo_ids"]["hero_id"]))
    assert player.get(foreign + "/context").status_code == 403
    assert player.post(foreign + "/character-binding", json=payload).status_code == 403
    assert player.get(path + "/context").get_json() == initial
    # A different character's context never receives this character's authored secrets.
    assert "SELF_PRIVATE_MAP" not in admin.get(foreign + "/context").get_data(as_text=True)
    # Broad scene inspection is not permission to inspect private character identity.
    simulation = app.extensions["simulation"]
    ids = app.extensions["demo_ids"]
    simulation.grant_authority(
        ids["world_id"], ids["actor_id"], roles=set(), capabilities={"world.read", "world.read.all"}
    )
    assert admin.get(path + "/character-binding", query_string={"run_id": run}).status_code == 403
    assert admin.get(path + "/context").get_json()["situation"]["identity"] is None
