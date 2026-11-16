from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from kernel.api.app import create_app
from kernel.contracts import CommandProposal
from kernel.postgres_repository import PostgresCommandRepository
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_trade_offers_api import OFFERS, identity, offer, prepare_trade, totals

pytestmark = pytest.mark.integration


def test_trade_escrow_restart_expiry_late_retry_and_recorded_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app, game)
    admin, player, card, path, run, target, base = game
    branch = uuid.UUID(base["branch_id"])
    original = app.extensions["world_runner"].snapshot().states.get(branch)
    conserved = totals(original, "food"), totals(original, "SPEAR")
    sold = command(
        player, base, card, "tabletop.economy.trade", {"offer_id": identity(buy)}, "sell"
    )
    assert sold.status_code == 200, sold.get_json()
    advance_clock(admin, base, 6)
    restored, client = player_after_restart(tmp_path, player)
    scene = client.get(path + "/scene").get_json()
    visible = next(row for row in scene["perceived_entities"] if row["entity_id"] == maker)
    assert visible["trade_offers"][0]["offer_id"] == identity(sell)
    mark = durable_mark(integration_stack, base)
    retry = command(
        client, base, card, "tabletop.economy.trade", {"offer_id": identity(buy)}, "sell"
    )
    # The scene synchronization cursor is current; the canonical receipt is original.
    for field in ("result", "event", "state_hash"):
        assert retry.get_json()[field] == sold.get_json()[field]
    assert durable_mark(integration_stack, base) == mark
    bought = command(
        client, base, card, "tabletop.economy.trade", {"offer_id": identity(sell)}, "buy"
    )
    assert bought.status_code == 200, bought.get_json()
    _, operator = fresh_client(tmp_path)
    short = offer(
        operator, base, maker, side="BUY", item="herb", price=4, quantity=2, ttl=10, key="expiring"
    )
    advance_clock(operator, base, 16)
    restarted, client = player_after_restart(tmp_path, player)
    state = restarted.extensions["world_runner"].snapshot().states.get(branch)
    assert identity(short) not in state.projections[OFFERS]
    assert (totals(state, "food"), totals(state, "SPEAR")) == conserved
    mark = durable_mark(integration_stack, base)
    expired = command(
        client, base, card, "tabletop.economy.trade", {"offer_id": identity(short)}, "expired"
    )
    assert expired.status_code == 400 and durable_mark(integration_stack, base) == mark
    _, operator = fresh_client(tmp_path)
    replay = operator.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_trade_publication_failure_rolls_back_escrow_both_resources_and_both_costs(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app, game)
    admin, player, card, path, run, target, base = game
    branch = uuid.UUID(base["branch_id"])
    before = app.extensions["world_runner"].snapshot().states.get(branch)
    expected = before.projections
    mark = durable_mark(integration_stack, base)
    original = PostgresCommandRepository._insert_event

    def fail(cursor, event):
        original(cursor, event)
        raise ValueError("injected trade publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCommandRepository, "_insert_event", staticmethod(fail))
        failed = command(
            player, base, card, "tabletop.economy.trade", {"offer_id": identity(buy)}, "sell"
        )
        assert failed.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restored, client = player_after_restart(tmp_path, player)
    state = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert state.projections == expected
    accepted = command(
        client, base, card, "tabletop.economy.trade", {"offer_id": identity(buy)}, "sell"
    )
    assert accepted.status_code == 200, accepted.get_json()
    state = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert state.projections["tabletop.action_time"][maker]["ready_seconds"] == 6
    assert state.projections["tabletop.action_time"][card["entity_id"]]["ready_seconds"] == 6


def test_two_separate_workers_accept_same_offer_once(integration_stack, monkeypatch, tmp_path):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app, game)
    admin, player, card, path, run, target, base = game
    # Obtain a real player's authorized actor from the authenticated API rather than
    # elevating a controller or granting a worker world-manager authority.
    actor_id = player.get("/api/v2/auth/session").get_json()["user"]["actor_id"]
    sources = [
        create_app(artifact_root=tmp_path).extensions["world_runner"].snapshot() for _ in range(2)
    ]
    intent = CommandProposal(
        **base,
        actor_id=actor_id,
        embodied_entity_id=card["entity_id"],
        command_type="tabletop.economy.trade",
        parameters={"offer_id": identity(buy)},
        idempotency_key="concurrent-sell",
    )
    mark = durable_mark(integration_stack, base)
    with ThreadPoolExecutor(max_workers=2) as workers:
        receipts = list(workers.map(lambda source: source.submit(intent), sources))
    assert receipts[0].event.event_id == receipts[1].event.event_id
    after = durable_mark(integration_stack, base)
    assert after[0] == mark[0] + 1 and all(
        a == b + 1 for a, b in zip(after[2:], mark[2:], strict=True)
    )
    restored, client = player_after_restart(tmp_path, player)
    state = restored.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    assert state.projections["tabletop.entities"][card["entity_id"]]["gold"] == 5
    assert state.projections["tabletop.entities"][maker]["inventory"]["SPEAR"] == 1
    assert identity(buy) not in state.projections[OFFERS]
