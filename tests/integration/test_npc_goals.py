from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest

from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_npc_goals import (
    advance_game,
    clock_path,
    configure_subjective,
    runtime_path,
    say,
)
from tests.unit.kernel.test_world_time import NOW, api_command

pytestmark = pytest.mark.integration


def test_two_card_associations_serialize_without_overwriting_authored_content(
    integration_stack, monkeypatch, tmp_path
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from domains.tabletop.portal import PostgresPortalRepository

    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, player_card, player_path, run, target, base = game
    cards = [
        admin.post(
            "/api/v2/player/characters",
            json={
                "world_id": base["world_id"],
                "name": "NPC " + str(i),
                "authored_identity": {"backstory": "PRESERVE_AUTHORED_CARD"},
            },
        ).get_json()
        for i in range(2)
    ]
    barrier = Barrier(2)
    actor = app.extensions["demo_ids"]["actor_id"]

    def bind(card):
        repository = PostgresPortalRepository(integration_stack.database_url)
        barrier.wait(timeout=5)
        try:
            return repository.associate_character(
                uuid.UUID(card["character_id"]),
                uuid.UUID(base["world_id"]),
                uuid.UUID(target),
                actor_id=actor,
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(bind, cards))
    assert sum(row is not None for row in results) == 1
    repository = PostgresPortalRepository(integration_stack.database_url)
    winner = next(row for row in results if row is not None)
    assert (
        repository.associate_character(
            winner.character_id, uuid.UUID(base["world_id"]), uuid.UUID(target), actor_id=actor
        )
        == winner
    )
    for card in cards:
        current = repository.get_character(uuid.UUID(card["character_id"]))
        assert current.authored_identity.backstory == "PRESERVE_AUTHORED_CARD"
        assert len(repository.character_revisions(current.character_id, actor_id=actor)) == 1


def executor(admin, base):
    response = admin.post(
        "/api/v2/actors",
        json={
            "world_id": base["world_id"],
            "display_name": "NPC goals clock",
            "kind": "AGENT",
            "capabilities": ["world.read", "action.propose", "action.commit", "mind.read.all"],
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["actor_id"]


def test_goal_inputs_and_changes_are_atomic_retryable_private_and_restart_safe(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    data = configure_subjective(app, game)
    game, card, path, association, config = data
    admin, player, player_card, player_path, run, target, base = game
    advance_game(admin, base, 20)
    speech = say(
        player,
        base,
        player_card,
        "motive_importance",
        {"motive": "CURIOSITY", "importance": 100},
        subject_id=target,
    )
    before = admin.get(runtime_path(base)).get_json(), admin.get(clock_path(base)).get_json()
    repository = app.extensions["simulation"].durable_repository
    original = repository._insert_perceptions

    def fail(*args):
        raise RuntimeError("test motivation rollback after ledger")

    proposal = {
        **base,
        "command_type": "tabletop.clock.advance",
        "idempotency_key": "new-belief",
        "parameters": {"expected_epoch": 1, "expected_seconds": 20, "to_seconds": 40},
    }
    repository._insert_perceptions = fail
    try:
        assert admin.post("/api/v2/commands", json=proposal).status_code == 500
    finally:
        repository._insert_perceptions = original
    assert (
        admin.get(runtime_path(base)).get_json(),
        admin.get(clock_path(base)).get_json(),
    ) == before
    accepted = admin.post("/api/v2/commands", json=proposal)
    assert accepted.status_code == 200, accepted.get_json()
    restored = create_app(artifact_root=tmp_path).test_client()
    restored.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    assert restored.post("/api/v2/commands", json=proposal).get_json() == accepted.get_json()
    row = restored.get(runtime_path(base)).get_json()["routines"][target]
    assert row["planner"]["selected"] == "explore"
    assert row["planner"]["spent"] == {"neighbors": 20, "explore": 20}
    assert speech["event"]["event_id"] in row["motivation"]["source_event_ids"]
    assert (
        row["motivation"]["binding_id"]
        == admin.get(path + "/character-binding?run_id=" + run).get_json()["binding"]["binding_id"]
    )
    say(
        player,
        base,
        player_card,
        "motive_importance",
        {"motive": "CARE", "importance": 100},
        subject_id=target,
        key="changed-conviction",
    )
    assert restored.post("/api/v2/commands", json=proposal).get_json() == accepted.get_json()
    advance_game(restored, base, 60)
    current = restored.get(runtime_path(base)).get_json()["routines"][target]
    assert current["planner"]["spent"] == {"neighbors": 40, "explore": 20}
    assert current["motivation"]["input_hash"] != row["motivation"]["input_hash"]
    assert player.get(runtime_path(base)).status_code == 403
    assert (
        player.put(association, json={"character_id": player_card["character_id"]}).status_code
        == 403
    )
    scene = player.get(player_path + "/scene").get_json()
    for private in ("PRIVATE_NPC_VOW", "motivation", "belief_ids", "input_hash", "binding_id"):
        assert private not in str(scene)
    replay = restored.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()
    assert replay["verified"]
    body = replay["projections"]["tabletop.entities"][target]
    assert body["hp"] == 100 and body["weeded_units"] == 40


def test_two_actual_workers_and_restart_choose_from_new_beliefs(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app, game)
    admin, player, player_card, player_path, run, target, base = game
    agent = executor(admin, base)

    def workers(until, count):
        clock = admin.get(clock_path(base)).get_json()["clock"]
        api_command(
            admin,
            base,
            "tabletop.clock.configure",
            {
                "expected_epoch": clock["epoch"],
                "executor_actor_id": agent,
                "seconds_per_tick": 10,
                "until_seconds": until,
                "paused": False,
                "wall_time": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
            "start:" + str(until),
        )
        children = [
            subprocess.Popen(
                [sys.executable, "main.py", "world-runner"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(count)
        ]
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                value = admin.get(clock_path(base)).get_json()["clock"]
                if value["seconds"] == until:
                    assert value["paused"]
                    return
                assert all(child.poll() is None for child in children)
                time.sleep(0.1)
            pytest.fail("NPC goal workers did not reach finite boundary")
        finally:
            for child in children:
                child.terminate()
            for child in children:
                child.wait(timeout=10)

    workers(30, 2)
    assert admin.get(runtime_path(base)).get_json()["routines"][target]["planner"]["spent"] == {
        "neighbors": 30
    }
    speech = say(
        player,
        base,
        player_card,
        "motive_importance",
        {"motive": "CURIOSITY", "importance": 100},
        subject_id=target,
    )
    workers(60, 1)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert row["planner"]["spent"] == {"neighbors": 30, "explore": 30}
    assert speech["event"]["event_id"] in row["motivation"]["source_event_ids"]
    assert admin.get(f"/api/v2/branches/{base['branch_id']}/replay").get_json()["verified"]


def test_revoked_mind_access_fences_a_stale_clock_without_partial_goal_progress(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app, game)
    admin, player, player_card, player_path, run, target, base = game
    agent = executor(admin, base)
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": agent,
            "seconds_per_tick": 10,
            "paused": False,
            "wall_time": NOW.isoformat(),
        },
        "start",
    )
    stale = app.extensions["world_runner"].snapshot()
    before = admin.get(runtime_path(base)).get_json(), admin.get(clock_path(base)).get_json()
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM sim.actor_capabilities WHERE world_id=%s AND actor_id=%s "
            "AND capability='mind.read.all'",
            (base["world_id"], agent),
        )
    with pytest.raises(PermissionError):
        stale.submit(
            CommandProposal(
                **base,
                actor_id=uuid.UUID(agent),
                command_type="tabletop.clock.tick",
                idempotency_key="revoked-mind",
                parameters={
                    "epoch": 2,
                    "step": 0,
                    "wall_time": (NOW + timedelta(seconds=2)).isoformat(),
                },
            )
        )
    assert (
        admin.get(runtime_path(base)).get_json(),
        admin.get(clock_path(base)).get_json(),
    ) == before
