from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import pytest

from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from kernel.postgres_repository import PostgresCommandRepository
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_quest_evidence_api import QUESTS, accepted, completed, prepare_quest
from tests.unit.kernel.test_tactical_choices import command

pytestmark = pytest.mark.integration


def test_quest_outcomes_reward_restart_late_retry_provenance_and_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app, game)
    admin, player, card, path, run, target, base = game
    accepted(player, base, card, quest)
    move_id, trade_id = completed(admin, player, base, card, buy)
    advance_clock(admin, base, 13)
    restarted, client = player_after_restart(tmp_path, player)
    state = restarted.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    assert state.projections[QUESTS][quest]["status"] == "READY"
    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT command_id,command_type FROM sim.command_log "
            "WHERE branch_id=%s AND command_id IN (%s,%s)",
            (base["branch_id"], move_id, trade_id),
        )
        sources = {str(identity): kind for identity, kind in cursor.fetchall()}
    assert sources == {move_id: "tabletop.spatial.move", trade_id: "tabletop.economy.trade"}
    evidence = state.projections[QUESTS][quest]["evidence"]
    assert [e["last_source_command_id"] for e in evidence] == [move_id, trade_id]
    paid = command(client, base, card, "tabletop.quest.claim", {"quest_id": quest}, "reward")
    assert paid.status_code == 200, paid.get_json()
    _, operator = fresh_client(tmp_path)
    advance_clock(operator, base, 19)
    restored, reader = player_after_restart(tmp_path, player)
    mark = durable_mark(integration_stack, base)
    retry = command(reader, base, card, "tabletop.quest.claim", {"quest_id": quest}, "reward")
    for field in ("result", "event", "state_hash"):
        assert retry.get_json()[field] == paid.get_json()[field]
    second = command(
        reader, base, card, "tabletop.quest.claim", {"quest_id": quest}, "reward-again"
    )
    assert second.status_code == 400 and durable_mark(integration_stack, base) == mark
    state = restored.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    body = state.projections["tabletop.entities"][card["entity_id"]]
    assert body["gold"] == 12 and body["inventory"]["food"] == 1
    _, operator = fresh_client(tmp_path)
    replay = operator.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


@pytest.mark.parametrize("phase", ["movement", "reward"])
def test_outcome_and_quest_evidence_roll_back_together_on_publication_failure(
    integration_stack, monkeypatch, tmp_path, phase
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app, game)
    admin, player, card, path, run, target, base = game
    accepted(player, base, card, quest)
    if phase == "reward":
        completed(admin, player, base, card, buy)
        advance_clock(admin, base, 13)
    else:
        advance_clock(admin, base, 6)
    kind, parameters = (
        ("tabletop.quest.claim", {"quest_id": quest})
        if phase == "reward"
        else ("tabletop.spatial.move", {"dx": 1, "dy": 0})
    )
    branch = uuid.UUID(base["branch_id"])
    before = app.extensions["world_runner"].snapshot().states.get(branch).projections
    mark = durable_mark(integration_stack, base)
    original = PostgresCommandRepository._insert_event

    def fail(cursor, event):
        original(cursor, event)
        raise ValueError("injected quest evidence publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCommandRepository, "_insert_event", staticmethod(fail))
        response = command(player, base, card, kind, parameters, "failed-outcome")
        assert response.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restored, reader = player_after_restart(tmp_path, player)
    assert restored.extensions["world_runner"].snapshot().states.get(branch).projections == before
    moved = command(reader, base, card, kind, parameters, "failed-outcome")
    assert moved.status_code == 200, moved.get_json()
    state = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert state.projections[QUESTS][quest]["evidence"][0]["progress"] == 1
    if phase == "reward":
        assert state.projections[QUESTS][quest]["status"] == "CLAIMED"
        assert state.projections["tabletop.entities"][card["entity_id"]]["gold"] == 12


def test_separate_workers_retry_reward_once_and_reject_new_duplicate_claim(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app, game)
    admin, player, card, path, run, target, base = game
    accepted(player, base, card, quest)
    completed(admin, player, base, card, buy)
    advance_clock(admin, base, 13)
    actor_id = player.get("/api/v2/auth/session").get_json()["user"]["actor_id"]
    sources = [
        create_app(artifact_root=tmp_path).extensions["world_runner"].snapshot() for _ in range(2)
    ]
    intent = CommandProposal(
        **base,
        actor_id=actor_id,
        embodied_entity_id=card["entity_id"],
        command_type="tabletop.quest.claim",
        parameters={"quest_id": quest},
        idempotency_key="concurrent-reward",
    )
    mark = durable_mark(integration_stack, base)
    with ThreadPoolExecutor(max_workers=2) as workers:
        receipts = list(workers.map(lambda source: source.submit(intent), sources))
    assert receipts[0].event.event_id == receipts[1].event.event_id
    after = durable_mark(integration_stack, base)
    assert after[0] == mark[0] + 1 and all(
        a == b + 1 for a, b in zip(after[2:], mark[2:], strict=True)
    )
    with pytest.raises(ValueError):
        sources[1].submit(intent.model_copy(update={"idempotency_key": "second-reward"}))
    assert durable_mark(integration_stack, base) == after
