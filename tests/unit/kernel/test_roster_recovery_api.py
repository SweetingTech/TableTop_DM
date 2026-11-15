from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def test_dm_human_runtime_still_controls_an_unowned_npc(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, _, card, _, _, run, _ = setup_bound_character(app)
    ids = app.extensions["demo_ids"]
    body = str(uuid.uuid4())
    scope = {"world_id": card["world_id"], "branch_id": str(ids["branch_id"]), "run_id": run}
    assert (
        admin.post(
            "/api/v2/commands",
            json={
                **scope,
                "command_type": "tabletop.entity.spawn",
                "parameters": {
                    "entity_id": body,
                    "name": "Unowned NPC",
                    "entity_type": "NPC",
                    "public_state": {"x": 1, "y": 0},
                },
                "idempotency_key": "npc-runtime",
            },
        ).status_code
        == 200
    )
    path = f"/api/v2/worlds/{card['world_id']}/branches/{ids['branch_id']}/entities/{body}"
    response = admin.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "HUMAN",
            "expected_epoch": 0,
            "idempotency_key": "dm-play-npc",
        },
    )
    assert response.status_code == 200
    response = admin.post(
        "/api/v2/commands",
        json={
            **scope,
            "command_type": "tabletop.dialogue.speak",
            "embodied_entity_id": body,
            "parameters": {"text": "Welcome to the yard."},
            "control_epoch": response.get_json()["state"]["epoch"],
            "idempotency_key": "npc-welcome",
        },
    )
    assert response.status_code == 200, response.get_json()


def _replacement(player, world):
    response = player.post(
        "/api/v2/player/characters", json={"world_id": world, "name": "Replacement"}
    )
    assert response.status_code == 201
    return response.get_json()


@pytest.mark.parametrize("invalid", ["missing", "foreign-owner", "foreign-world"])
def test_invalid_character_assignment_preserves_existing_seat_authority_and_world(
    monkeypatch, tmp_path, invalid
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, path, _, user = setup_bound_character(app)
    selected = str(uuid.uuid4())
    if invalid == "foreign-owner":
        _, _, other, _, _, _, _ = setup_bound_character(app)
        selected = other["character_id"]
    elif invalid == "foreign-world":
        other_world = admin.post(
            "/api/v2/worlds", json={"name": "Other assignment world"}
        ).get_json()["world_id"]
        assert (
            admin.put(
                f"/api/v2/admin/users/{user}/worlds/{other_world}/roles", json={"roles": ["PLAYER"]}
            ).status_code
            == 200
        )
        selected = _replacement(player, other_world)["character_id"]
    state = app.extensions["simulation"].states.get(app.extensions["demo_ids"]["branch_id"])
    version, digest = state.version, state.state_hash
    response = admin.put(
        f"/api/v2/dm/games/{game['game_id']}/members",
        json={"user_id": user, "character_id": selected},
    )
    assert response.status_code == (404 if invalid == "missing" else 400)
    saved = next(
        row
        for row in admin.get("/api/v2/games").get_json()["items"]
        if row["game_id"] == game["game_id"]
    )
    assert saved["members"][0]["character_id"] == card["character_id"]
    assert (state.version, state.state_hash) == (version, digest)
    assert player.get(path + "/scene").status_code == 200


@pytest.mark.parametrize("run_status", [None, "COMPLETED"])
def test_assignment_without_unfinished_live_run_preserves_roster(monkeypatch, tmp_path, run_status):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, _, run, user = setup_bound_character(app)
    replacement = _replacement(player, card["world_id"])
    simulation = app.extensions["simulation"]
    if run_status is None:
        del simulation.runs[uuid.UUID(run)]
    else:
        simulation.runs[uuid.UUID(run)] = simulation.runs[uuid.UUID(run)].model_copy(
            update={"status": run_status}
        )
    before_entities = dict(simulation.entities)
    response = admin.put(
        f"/api/v2/dm/games/{game['game_id']}/members",
        json={"user_id": user, "character_id": replacement["character_id"]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_operation"
    saved = next(
        row
        for row in admin.get("/api/v2/games").get_json()["items"]
        if row["game_id"] == game["game_id"]
    )
    assert saved["members"][0]["character_id"] == card["character_id"]
    staged = next(
        row
        for row in player.get("/api/v2/player/characters").get_json()["items"]
        if row["character_id"] == replacement["character_id"]
    )
    assert staged["entity_id"] is None
    assert simulation.entities == before_entities


def test_failed_persona_binding_does_not_publish_replacement_seat_and_retry_recovers(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, _, _, user = setup_bound_character(app)
    replacement = _replacement(player, card["world_id"])
    bindings = app.extensions["character_bindings"]
    save = bindings.save

    def fail(*args, **kwargs):
        raise ValueError("injected binding failure")

    monkeypatch.setattr(bindings, "save", fail)
    path = f"/api/v2/dm/games/{game['game_id']}/members"
    payload = {"user_id": user, "character_id": replacement["character_id"]}
    assert admin.put(path, json=payload).status_code == 400
    saved = next(
        row
        for row in admin.get("/api/v2/games").get_json()["items"]
        if row["game_id"] == game["game_id"]
    )
    assert saved["members"][0]["character_id"] == card["character_id"]
    monkeypatch.setattr(bindings, "save", save)
    assert admin.put(path, json=payload).status_code == 200
    simulation = app.extensions["simulation"]
    entities, events, binding_count = (
        len(simulation.entities),
        len(simulation.events),
        len(bindings.rows),
    )
    assert admin.put(path, json=payload).status_code == 200
    assert (len(simulation.entities), len(simulation.events), len(bindings.rows)) == (
        entities,
        events,
        binding_count,
    )


def test_removal_revokes_control_fences_runner_and_rejoin_preserves_body_and_binding(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, path, run, user = setup_bound_character(app)
    response = player.post(
        path + "/control",
        json={"run_id": run, "expected_epoch": 0, "mode": "AUTONOMOUS", "idempotency_key": "leave"},
    )
    assert response.status_code == 200
    before = response.get_json()["state"]
    binding_ids = set(app.extensions["character_bindings"].rows)
    simulation = app.extensions["simulation"]
    scope = tuple(
        uuid.UUID(before[key]) for key in ("world_id", "branch_id", "run_id", "entity_id")
    )
    assert admin.delete(f"/api/v2/dm/games/{game['game_id']}/members/{user}").status_code == 204
    assert player.get(path + "/scene").status_code == 403
    assert player.get(path + "/context").status_code == 403
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "expected_epoch": before["epoch"],
                "mode": "HUMAN",
                "idempotency_key": "stale",
            },
        ).status_code
        == 403
    )
    state = simulation.controller_states[scope]
    assert state.mode == "PAUSED" and state.epoch == before["epoch"] + 1
    assert simulation.entities[(scope[1], scope[3])].controller_actor_id is None
    assert (
        uuid.UUID(card["entity_id"])
        not in simulation.authority(scope[0], state.owner_actor_id).controlled_entity_ids
    )
    assert set(app.extensions["character_bindings"].rows) == binding_ids
    assert (
        admin.put(
            f"/api/v2/dm/games/{game['game_id']}/members",
            json={"user_id": user, "character_id": card["character_id"]},
        ).status_code
        == 200
    )
    assert player.get(path + "/scene").status_code == 200
    assert simulation.controller_states[scope].mode == "HUMAN"
    assert simulation.controller_states[scope].epoch == before["epoch"] + 2
    assert set(app.extensions["character_bindings"].rows) == binding_ids


def test_reassignment_revokes_old_body_and_failed_finalization_keeps_old_seat(
    monkeypatch, tmp_path
):
    from domains.tabletop.portal import InMemoryPortalRepository

    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, old_path, _, user = setup_bound_character(app)
    replacement = _replacement(player, card["world_id"])
    original = InMemoryPortalRepository.set_member

    def fail_after_write(repository, game_id, member):
        original(repository, game_id, member)
        raise ValueError("injected finalization failure")

    monkeypatch.setattr(InMemoryPortalRepository, "set_member", fail_after_write)
    path = f"/api/v2/dm/games/{game['game_id']}/members"
    payload = {"user_id": user, "character_id": replacement["character_id"]}
    assert admin.put(path, json=payload).status_code == 400
    assert player.get(old_path + "/scene").status_code == 200
    saved = next(
        row
        for row in admin.get("/api/v2/games").get_json()["items"]
        if row["game_id"] == game["game_id"]
    )
    assert saved["members"][0]["character_id"] == card["character_id"]
    staged = next(
        row
        for row in player.get("/api/v2/player/characters").get_json()["items"]
        if row["character_id"] == replacement["character_id"]
    )
    simulation = app.extensions["simulation"]
    assert (
        simulation.entities[
            (app.extensions["demo_ids"]["branch_id"], uuid.UUID(staged["entity_id"]))
        ].controller_actor_id
        is None
    )
    monkeypatch.setattr(InMemoryPortalRepository, "set_member", original)
    assert admin.put(path, json=payload).status_code == 200
    assert player.get(old_path + "/scene").status_code == 403


def test_removal_keeps_control_if_another_game_has_the_same_character(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, game, path, _, user = setup_bound_character(app)
    other = admin.post(
        "/api/v2/dm/games", json={"world_id": card["world_id"], "name": "Other table"}
    ).get_json()
    assert (
        admin.put(
            f"/api/v2/dm/games/{other['game_id']}/members",
            json={"user_id": user, "character_id": card["character_id"]},
        ).status_code
        == 200
    )
    assert admin.delete(f"/api/v2/dm/games/{game['game_id']}/members/{user}").status_code == 204
    assert player.get(path + "/scene").status_code == 200
    assert admin.delete(f"/api/v2/dm/games/{other['game_id']}/members/{user}").status_code == 204
    assert player.get(path + "/scene").status_code == 403
