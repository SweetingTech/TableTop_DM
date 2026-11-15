from __future__ import annotations

import uuid

import pytest

from cognition.projector import WorldEventProjector
from domains.tabletop.portal import PostgresPortalRepository
from kernel.api.app import create_app
from kernel.database import transaction
from kernel.errors import AuthorizationDenied
from kernel.postgres_repository import PostgresCommandRepository
from tests.integration.test_controller_runner import setup

pytestmark = pytest.mark.integration


def test_existing_world_viewpoints_follow_reassignment_from_another_api_process(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, game, old_path, _, user) = setup(
        integration_stack, monkeypatch, tmp_path
    )
    replacement = player.post(
        "/api/v2/player/characters",
        json={"world_id": card["world_id"], "name": "Other API assignment"},
    ).get_json()
    other = create_app(artifact_root=tmp_path)
    dm = other.test_client()
    dm.environ_base.update(admin.environ_base)
    assert (
        dm.put(
            f"/api/v2/dm/games/{game['game_id']}/members",
            json={"user_id": user, "character_id": replacement["character_id"]},
        ).status_code
        == 200
    )
    updated = next(
        row
        for row in player.get("/api/v2/player/characters").get_json()["items"]
        if row["character_id"] == replacement["character_id"]
    )
    viewpoints = player.get(f"/api/v2/worlds/{card['world_id']}/viewpoints").get_json()["items"]
    assert {row["entity_id"] for row in viewpoints} == {updated["entity_id"]}
    assert viewpoints[0]["can_act"] is True
    assert player.get(old_path + "/scene").status_code == 403
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_dm_human_runtime_on_unowned_npc_retains_existing_authority(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, _, card, _, _, run, _) = setup(integration_stack, monkeypatch, tmp_path)
    body = str(uuid.uuid4())
    branch = str(
        app.extensions["simulation"].worlds[uuid.UUID(card["world_id"])].canonical_branch_id
    )
    scope = {"world_id": card["world_id"], "branch_id": branch, "run_id": run}
    assert (
        admin.post(
            "/api/v2/commands",
            json={
                **scope,
                "command_type": "tabletop.entity.spawn",
                "parameters": {
                    "entity_id": body,
                    "name": "DM runtime NPC",
                    "entity_type": "NPC",
                    "public_state": {"x": 1, "y": 0},
                },
                "idempotency_key": "npc-runtime",
            },
        ).status_code
        == 200
    )
    path = f"/api/v2/worlds/{card['world_id']}/branches/{branch}/entities/{body}"
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
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_failed_controller_event_rolls_back_roster_grants_ledger_and_outbox(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, game, old_path, _, user) = setup(
        integration_stack, monkeypatch, tmp_path
    )
    replacement = player.post(
        "/api/v2/player/characters",
        json={"world_id": card["world_id"], "name": "Atomic finalization"},
    ).get_json()
    original = PostgresCommandRepository._insert_event

    def fail(cursor, event):
        if event.event_type == "tabletop.entity.set_controllers":
            raise RuntimeError("injected controller event persistence failure")
        return original(cursor, event)

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCommandRepository, "_insert_event", staticmethod(fail))
        assert (
            admin.put(
                f"/api/v2/dm/games/{game['game_id']}/members",
                json={"user_id": user, "character_id": replacement["character_id"]},
            ).status_code
            == 500
        )
    assert player.get(old_path + "/scene").status_code == 200
    with transaction(
        actor_id=app.extensions["demo_ids"]["actor_id"], dsn=integration_stack.database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT character_id FROM tabletop.game_members WHERE game_id=%s AND user_id=%s",
                (game["game_id"], user),
            )
            assert str(cursor.fetchone()[0]) == card["character_id"]
            cursor.execute(
                "SELECT count(*) FROM sim.command_log WHERE world_id=%s "
                "AND command_type='tabletop.entity.set_controllers'",
                (card["world_id"],),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT count(*) FROM sim.events WHERE world_id=%s "
                "AND event_type='tabletop.entity.set_controllers'",
                (card["world_id"],),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT count(*) FROM sim.outbox WHERE payload->'event'->>'world_id'=%s "
                "AND payload->'event'->>'event_type'='tabletop.entity.set_controllers'",
                (card["world_id"],),
            )
            assert cursor.fetchone()[0] == 1
    assert (
        admin.put(
            f"/api/v2/dm/games/{game['game_id']}/members",
            json={"user_id": user, "character_id": replacement["character_id"]},
        ).status_code
        == 200
    )
    assert player.get(old_path + "/scene").status_code == 403
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_failed_roster_finalization_rolls_back_seat_and_control_then_restart_retry_recovers(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, game, old_path, _, user) = setup(
        integration_stack, monkeypatch, tmp_path
    )
    replacement = player.post(
        "/api/v2/player/characters",
        json={"world_id": card["world_id"], "name": "Recoverable replacement"},
    ).get_json()
    original = PostgresPortalRepository.set_member

    def fail_after_write(repository, game_id, member):
        original(repository, game_id, member)
        raise ValueError("injected final roster failure")

    monkeypatch.setattr(PostgresPortalRepository, "set_member", fail_after_write)
    path = f"/api/v2/dm/games/{game['game_id']}/members"
    payload = {"user_id": user, "character_id": replacement["character_id"]}
    assert admin.put(path, json=payload).status_code == 400
    assert player.get(old_path + "/scene").status_code == 200
    with transaction(
        actor_id=app.extensions["demo_ids"]["actor_id"], dsn=integration_stack.database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT character_id FROM tabletop.game_members WHERE game_id=%s AND user_id=%s",
                (game["game_id"], user),
            )
            assert str(cursor.fetchone()[0]) == card["character_id"]
            cursor.execute(
                "SELECT e.controller_actor_id FROM tabletop.characters c JOIN sim.entities e "
                "ON (e.world_id,e.id)=(c.world_id,c.entity_id) WHERE c.id=%s",
                (replacement["character_id"],),
            )
            assert cursor.fetchone()[0] is None
    monkeypatch.setattr(PostgresPortalRepository, "set_member", original)
    restarted = create_app(artifact_root=tmp_path)
    client = restarted.test_client()
    client.environ_base.update(admin.environ_base)
    response = client.put(path, json=payload)
    assert response.status_code == 200, response.get_json()
    assert player.get(old_path + "/scene").status_code == 403
    with transaction(
        actor_id=restarted.extensions["demo_ids"]["actor_id"], dsn=integration_stack.database_url
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM tabletop.character_bindings WHERE character_id=%s",
                (replacement["character_id"],),
            )
            assert cursor.fetchone()[0] == 1
    assert client.put(path, json=payload).status_code == 200
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)


def test_removal_revokes_runtime_owner_rls_and_queued_executor_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, game, path, run, user) = setup(
        integration_stack, monkeypatch, tmp_path
    )
    response = player.post(
        path + "/control",
        json={"run_id": run, "expected_epoch": 0, "mode": "AUTONOMOUS", "idempotency_key": "leave"},
    )
    assert response.status_code == 200, response.get_json()
    prior = response.get_json()["state"]
    actor = uuid.UUID(prior["owner_actor_id"])
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    runner = app.extensions["character_runner"]
    active = next(row for row in app.extensions["controllers"].due() if str(row.run_id) == run)
    queued = runner.decisions.decide(
        active.scope, active.executor_actor_id, "queued-before-removal", active
    ).outcome.proposal
    assert queued is not None
    restarted = create_app(artifact_root=tmp_path)
    client = restarted.test_client()
    client.environ_base.update(admin.environ_base)
    response = client.delete(f"/api/v2/dm/games/{game['game_id']}/members/{user}")
    assert response.status_code == 204, response.get_json()
    assert player.get(path + "/context").status_code == 403
    with transaction(actor_id=actor, dsn=integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT sim.runtime_controls_entity(%s,%s,%s)",
                (card["world_id"], prior["branch_id"], card["entity_id"]),
            )
            assert cursor.fetchone()[0] is False
            cursor.execute("SELECT count(*) FROM sim.entities WHERE id=%s", (card["entity_id"],))
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "UPDATE cognition.controller_assignments SET payload="
                "jsonb_set(jsonb_set(payload,'{mode}','\"AUTONOMOUS\"'),'{epoch}',"
                "to_jsonb((payload->>'epoch')::bigint+1)) WHERE entity_id=%s",
                (card["entity_id"],),
            )
            assert cursor.rowcount == 0
            cursor.execute(
                "SELECT count(*) FROM cognition.mind_states WHERE entity_id=%s",
                (card["entity_id"],),
            )
            assert cursor.fetchone()[0] == 0
    restored = create_app(artifact_root=tmp_path)
    state = restored.extensions["simulation"].controller_states[
        tuple(uuid.UUID(prior[key]) for key in ("world_id", "branch_id", "run_id", "entity_id"))
    ]
    assert state.mode == "PAUSED" and state.epoch == prior["epoch"] + 1
    assert not any(
        row.entity_id == uuid.UUID(card["entity_id"])
        for row in restored.extensions["controllers"].due()
    )
    with pytest.raises(AuthorizationDenied):
        restored.extensions["character_runner"].snapshot().submit(queued)
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
