from __future__ import annotations

import uuid

import pytest

from domains.tabletop.economy import OFFERS
from kernel.contracts import ActorKind
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_derived_combat_api import grant_items
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_timed_effects_api import physical_projection, projected_advance
from tests.unit.kernel.test_world_time import api_command, clock_game
from tests.unit.tabletop.test_domain_commands import domain as domain_fixture
from tests.unit.tabletop.test_domain_commands import proposal

pytestmark = pytest.mark.unit


def offer(
    admin, base, maker, *, side="SELL", item="food", quantity=3, price=2, ttl=86400, key="offer"
):
    return api_command(
        admin,
        base,
        "tabletop.economy.configure_offer",
        {
            "maker_id": maker,
            "side": side,
            "item": item,
            "quantity": quantity,
            "unit_price": price,
            "valid_for_seconds": ttl,
        },
        key,
    )


def identity(receipt):
    return receipt["result"]["result"]["offer_id"]


def prepare_trade(app, game=None):
    game = game or clock_game(app)
    admin, player, card, path, run, target, base = game
    grant_items(app, admin, base, card["entity_id"])
    maker = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": maker,
            "name": "Marketkeeper",
            "entity_type": "NPC",
            "public_state": {"hp": 12, "x": 1, "y": 1, "gold": 100, "inventory": {"food": 5}},
            "secret_state": {"notes": "HIDDEN_OFFER_BOOK"},
        },
        "merchant",
    )
    buy = offer(admin, base, maker, side="BUY", item="SPEAR", quantity=1, price=5, key="buy-spear")
    sell = offer(admin, base, maker)
    return game, maker, buy, sell


def totals(state, item):
    bodies = state.projections["tabletop.entities"].values()
    gold = sum(int(row.get("gold", 0)) for row in bodies)
    count = sum(int(row.get("inventory", {}).get(item, 0)) for row in bodies)
    for row in state.projections.get(OFFERS, {}).values():
        if row["side"] == "BUY":
            gold += row["remaining_quantity"] * row["unit_price"]
        elif row["item"] == item:
            count += row["remaining_quantity"]
    return gold, count


def test_authorized_price_escrow_partial_trade_contact_costs_and_late_retry(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = totals(state, "SPEAR"), totals(state, "food")
    sold = command(
        player,
        base,
        card,
        "tabletop.economy.trade",
        {"offer_id": identity(buy), "quantity": 1},
        "sell-spear",
    )
    assert sold.status_code == 200, sold.get_json()
    assert sold.get_json()["result"]["result"]["price"] == 5
    assert state.projections["tabletop.entities"][card["entity_id"]]["gold"] == 5
    assert identity(buy) not in state.projections[OFFERS]
    assert state.projections["tabletop.action_time"][maker]["ready_seconds"] == 6
    mark = state.version, state.state_hash
    early = command(
        player, base, card, "tabletop.economy.trade", {"offer_id": identity(sell)}, "too-soon"
    )
    assert early.status_code == 400 and (state.version, state.state_hash) == mark
    advance_clock(admin, base, 6)
    bought = command(
        player, base, card, "tabletop.economy.trade", {"offer_id": identity(sell)}, "food"
    )
    assert bought.status_code == 200, bought.get_json()
    assert state.projections["tabletop.entities"][card["entity_id"]]["gold"] == 3
    assert state.projections[OFFERS][identity(sell)]["remaining_quantity"] == 2
    assert (totals(state, "SPEAR"), totals(state, "food")) == before
    mark = state.version, state.state_hash
    retry = command(
        player,
        base,
        card,
        "tabletop.economy.trade",
        {"offer_id": identity(buy), "quantity": 1},
        "sell-spear",
    )
    assert retry.status_code == 200
    for field in ("result", "event", "state_hash"):
        assert retry.get_json()[field] == sold.get_json()[field]
    assert (state.version, state.state_hash) == mark


def test_offer_visibility_and_character_context_do_not_reveal_internal_ids_or_private_accounts(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    scene = player.get(path + "/scene").get_json()
    market = next(row for row in scene["perceived_entities"] if row["entity_id"] == maker)
    assert {row["offer_id"] for row in market["trade_offers"]} == {identity(buy), identity(sell)}
    situation = player.get(path + "/context", query_string={"run_id": run}).get_json()["situation"]
    text = str(situation)
    for hidden in (
        identity(buy),
        identity(sell),
        "HIDDEN_OFFER_BOOK",
        "source_command_id",
        "expires_seconds",
        "remaining_quantity",
    ):
        assert hidden not in text
    assert "food" in text and "unit_price" in text


@pytest.mark.parametrize(
    "parameters",
    [
        {"unit_price": 0},
        {"direction": "BUY"},
        {"item": "food"},
        {"buyer_id": str(uuid.UUID(int=1))},
        {"quantity": 100000},
    ],
)
def test_taker_cannot_override_offer_terms_and_invalid_actions_leave_no_writes(
    monkeypatch, tmp_path, parameters
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    mark = state.version, state.state_hash
    response = command(
        player,
        base,
        card,
        "tabletop.economy.trade",
        {"offer_id": identity(sell), **parameters},
        "forge",
    )
    assert response.status_code == 400, response.get_json()
    assert (state.version, state.state_hash) == mark
    forbidden = command(
        player,
        base,
        card,
        "tabletop.economy.configure_offer",
        {"maker_id": maker, "side": "BUY", "item": "SPEAR", "quantity": 1, "unit_price": 99},
        "fake-bid",
    )
    assert forbidden.status_code == 403
    assert (state.version, state.state_hash) == mark


@pytest.mark.parametrize("problem", ["far", "hidden", "asleep", "dead", "other_zone"])
def test_trade_requires_perceived_capable_contact_not_a_known_offer_id(
    monkeypatch, tmp_path, problem
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    if problem == "far":
        state.projections["tabletop.spatial.positions"][maker]["x"] = 10
    elif problem == "hidden":
        state.projections["tabletop.sensory_profiles"][maker]["invisible"] = True
    elif problem == "other_zone":
        state.projections["tabletop.spatial.positions"][maker]["zone_id"] = "elsewhere"
    else:
        state.projections["tabletop.entities"][maker][problem] = True
    mark = state.version, state.state_hash
    response = command(
        player, base, card, "tabletop.economy.trade", {"offer_id": identity(buy)}, "no-contact"
    )
    assert response.status_code == 400
    assert (state.version, state.state_hash) == mark


def test_expiry_refunds_carried_escrow_once_and_is_partition_invariant(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    extra = offer(
        admin, base, maker, side="BUY", item="herb", quantity=2, price=4, ttl=10, key="short-bid"
    )
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = totals(state, "herb")
    whole, split = state.working_copy(), state.working_copy()
    projected_advance(whole, 20)
    for end in (5, 9, 10, 20):
        projected_advance(split, end)
    assert physical_projection(whole) == physical_projection(split)
    assert identity(extra) not in whole.projections[OFFERS]
    assert totals(whole, "herb") == before
    advance_clock(admin, base, 10)
    mark = state.version, state.state_hash
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.economy.cancel_offer",
            "parameters": {"offer_id": identity(extra)},
            "idempotency_key": "no-double-refund",
        },
    )
    assert response.status_code == 400
    assert (state.version, state.state_hash) == mark


def test_controlled_issuer_reserves_owned_weapon_and_cannot_self_trade(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    grant_items(app, admin, base, card["entity_id"])
    posted = command(
        player,
        base,
        card,
        "tabletop.economy.offer",
        {"side": "SELL", "item": "SPEAR", "quantity": 1, "unit_price": 50},
        "own-offer",
    )
    assert posted.status_code == 200, posted.get_json()
    offer_id = identity(posted.get_json())
    assert all(delta["projection"] != OFFERS for delta in posted.get_json()["result"]["deltas"])
    assert "source_command_id" not in str(posted.get_json())
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    assert state.projections["tabletop.entities"][card["entity_id"]]["inventory"]["SPEAR"] == 0
    advance_clock(admin, base, 6)
    mark = state.version, state.state_hash
    response = command(player, base, card, "tabletop.economy.trade", {"offer_id": offer_id}, "self")
    assert response.status_code == 400 and (state.version, state.state_hash) == mark
    cancelled = command(
        player, base, card, "tabletop.economy.withdraw_offer", {"offer_id": offer_id}, "withdraw"
    )
    assert cancelled.status_code == 200, cancelled.get_json()
    assert state.projections["tabletop.entities"][card["entity_id"]]["inventory"]["SPEAR"] == 1
    mark = state.version, state.state_hash
    assert (
        command(
            player,
            base,
            card,
            "tabletop.economy.withdraw_offer",
            {"offer_id": offer_id},
            "withdraw",
        ).get_json()
        == cancelled.get_json()
    )
    assert (state.version, state.state_hash) == mark


def test_passive_trade_interrupts_maker_rest_and_prevents_second_simultaneous_response(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    grant_items(app, admin, base, card["entity_id"])
    posted = offer(admin, base, card["entity_id"], item="SPEAR", quantity=1, price=0)
    other = offer(
        admin, base, card["entity_id"], item="SHORTSWORD", quantity=1, price=0, key="other"
    )
    resting = command(player, base, card, "tabletop.rest.start", {"kind": "LONG"}, "rest")
    assert resting.status_code == 200, resting.get_json()
    taker = {"entity_id": target}
    accepted = command(
        admin, base, taker, "tabletop.economy.trade", {"offer_id": identity(posted)}, "take"
    )
    assert accepted.status_code == 200, accepted.get_json()
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    assert state.projections["tabletop.activities"][card["entity_id"]]["status"] == "CANCELLED"
    assert state.projections["tabletop.action_time"][card["entity_id"]]["ready_seconds"] == 6
    # A different capable taker is physically adjacent but cannot spend the resting maker twice.
    spawned = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": spawned,
            "name": "Second buyer",
            "entity_type": "NPC",
            "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
            "public_state": {"hp": 10, "x": 0, "y": 1},
        },
        "second-buyer",
    )
    mark = state.version, state.state_hash
    rejected = command(
        admin,
        base,
        {"entity_id": spawned},
        "tabletop.economy.trade",
        {"offer_id": identity(other)},
        "second-take",
    )
    assert rejected.status_code == 400, rejected.get_json()
    assert "counterparty is still completing" in rejected.get_json()["details"]
    assert (state.version, state.state_hash) == mark
    advance_clock(admin, base, 6)
    assert (
        command(
            admin,
            base,
            {"entity_id": spawned},
            "tabletop.economy.trade",
            {"offer_id": identity(other)},
            "second-take",
        ).status_code
        == 200
    )


@pytest.mark.parametrize("kind", [ActorKind.HUMAN, ActorKind.AGENT])
def test_same_offer_enforcement_and_conservation_for_human_and_agent_trials(kind):
    domain = domain_fixture.__wrapped__()
    actor = domain["actor"].model_copy(update={"kind": kind})
    merchant = domain["state"].projections["tabletop.entities"][str(domain["merchant"])]
    merchant.update(x=2, y=2)
    receipt = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.economy.configure_offer",
            {
                "maker_id": domain["merchant"],
                "side": "SELL",
                "item": "herb",
                "quantity": 2,
                "unit_price": 5,
            },
            "offer",
        ),
        actor,
    )
    before = totals(domain["state"], "herb")
    request = proposal(
        domain,
        "tabletop.economy.trade",
        {"offer_id": receipt.result.result["offer_id"], "quantity": 2},
        "trade",
    )
    trade = domain["bus"].execute(request, actor)
    assert trade.result.result["price"] == 10
    assert domain["bus"].execute(request, actor) == trade
    assert totals(domain["state"], "herb") == before
