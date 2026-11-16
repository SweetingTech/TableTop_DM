from __future__ import annotations

import uuid

import pytest

from domains.tabletop.quests.contracts import QUESTS
from kernel.contracts import ActorKind
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command, resources
from tests.unit.kernel.test_trade_offers_api import identity, prepare_trade
from tests.unit.kernel.test_world_time import api_command
from tests.unit.tabletop.test_domain_commands import domain as domain_fixture
from tests.unit.tabletop.test_domain_commands import proposal

pytestmark = pytest.mark.unit


def configure_quest(admin, base, giver, objectives, *, gold=7, items=None, key="quest"):
    return api_command(
        admin,
        base,
        "tabletop.quest.configure",
        {
            "giver_id": giver,
            "title": "A market errand",
            "description": "Help the marketkeeper.",
            "objectives": objectives,
            "reward_gold": gold,
            "reward_items": items or {},
        },
        key,
    )["result"]["result"]["quest_id"]


def prepare_quest(app, game=None):
    game, maker, buy, sell = prepare_trade(app, game)
    admin, player, card, path, run, target, base = game
    quest = configure_quest(
        admin,
        base,
        maker,
        [
            {"kind": "MOVE", "description": "Reach the road", "x": 1, "y": 0},
            {
                "kind": "TRADE",
                "description": "Deliver a spear",
                "side": "SELL",
                "counterparty_id": maker,
                "item": "SPEAR",
                "quantity": 1,
            },
        ],
        items={"food": 1},
    )
    return game, maker, buy, sell, quest


def accepted(player, base, card, quest):
    response = command(player, base, card, "tabletop.quest.accept", {"quest_id": quest}, "accept")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def completed(admin, player, base, card, buy):
    def submit(kind, parameters, key, identity):
        return player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": card["entity_id"],
                "command_id": identity,
                "command_type": kind,
                "parameters": parameters,
                "idempotency_key": key,
            },
        )

    move_id, trade_id = str(uuid.uuid4()), str(uuid.uuid4())
    advance_clock(admin, base, 6)
    moved = submit("tabletop.spatial.move", {"dx": 1, "dy": 0}, "road", move_id)
    assert moved.status_code == 200, moved.get_json()
    advance_clock(admin, base, 7)
    sold = submit("tabletop.economy.trade", {"offer_id": identity(buy)}, "deliver", trade_id)
    assert sold.status_code == 200, sold.get_json()
    return move_id, trade_id


def test_objectives_need_actual_actions_and_funded_reward_is_paid_once(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app)
    admin, player, card, path, run, target, base = game
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    assert state.projections["tabletop.entities"][maker]["gold"] == 88  # five reserved for the bid
    assert state.projections["tabletop.entities"][maker]["inventory"]["food"] == 1
    accepted(player, base, card, quest)
    mark = state.version, state.state_hash
    premature = command(player, base, card, "tabletop.quest.claim", {"quest_id": quest}, "claim")
    assert premature.status_code == 400 and (state.version, state.state_hash) == mark
    moved, sold = completed(admin, player, base, card, buy)
    row = state.projections[QUESTS][quest]
    assert row["status"] == "READY"
    assert [e["progress"] for e in row["evidence"]] == [1, 1]
    assert row["evidence"][0]["last_source_command_id"] == moved
    assert row["evidence"][1]["last_source_command_id"] == sold
    advance_clock(admin, base, 13)
    claimed = command(player, base, card, "tabletop.quest.claim", {"quest_id": quest}, "claim")
    assert claimed.status_code == 200, claimed.get_json()
    body = state.projections["tabletop.entities"][card["entity_id"]]
    assert body["gold"] == 12 and body["inventory"]["food"] == 1
    assert state.projections[QUESTS][quest]["status"] == "CLAIMED"
    advance_clock(admin, base, 19)
    mark = state.version, state.state_hash
    retry = command(player, base, card, "tabletop.quest.claim", {"quest_id": quest}, "claim")
    for field in ("result", "event", "state_hash"):
        assert retry.get_json()[field] == claimed.get_json()[field]
    second = command(
        player, base, card, "tabletop.quest.claim", {"quest_id": quest}, "second-claim"
    )
    assert second.status_code == 400 and (state.version, state.state_hash) == mark


@pytest.mark.parametrize(
    "extra",
    [
        {"amount": 100},
        {"target": 1},
        {"objective": "done"},
        {"reward_gold": 1000},
        {"source_command_id": str(uuid.uuid4())},
    ],
)
def test_progress_or_rewards_cannot_be_self_reported(monkeypatch, tmp_path, extra):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app)
    admin, player, card, path, run, target, base = game
    accepted(player, base, card, quest)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    mark = state.version, state.state_hash
    for kind in ("tabletop.quest.advance", "tabletop.quest.claim"):
        rejected = command(player, base, card, kind, {"quest_id": quest, **extra}, "forged")
        assert rejected.status_code == 400 and (state.version, state.state_hash) == mark


def test_public_quotes_and_personal_progress_hide_objective_provenance_and_other_owners(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app)
    admin, player, card, path, run, target, base = game
    scene = player.get(path + "/scene").get_json()
    giver = next(row for row in scene["perceived_entities"] if row["entity_id"] == maker)
    assert giver["quest_offers"][0]["quest_id"] == quest
    context = player.get(path + "/context", query_string={"run_id": run}).get_json()
    fiction = str(context["situation"])
    assert "A market errand" in fiction and "Deliver a spear" in fiction
    for private in (quest, maker, "source_command_id", "seen_entity_ids", "counterparty_id"):
        assert private not in fiction
    accepted(player, base, card, quest)
    scene = player.get(path + "/scene").get_json()
    own = next(row for row in scene["perceived_entities"] if row["entity_id"] == card["entity_id"])
    assert own["quests"][0]["status"] == "ACTIVE"
    other = next(row for row in scene["perceived_entities"] if row["entity_id"] == maker)
    assert not other["quests"] and not other["quest_offers"]


def test_offscreen_work_derives_only_new_committed_work_after_acceptance(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, worker, base = game
    advance_clock(admin, base, 10)  # Earlier work does not count toward a later promise.
    quest = configure_quest(
        admin, base, maker, [{"kind": "WEED", "description": "Clear four units", "units": 4}]
    )
    accepted(admin, base, {"entity_id": worker}, quest)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    advance_clock(admin, base, 16)
    assert state.projections[QUESTS][quest]["evidence"][0]["progress"] == 0
    advance_clock(admin, base, 19)
    assert state.projections[QUESTS][quest]["evidence"][0]["progress"] == 3
    advance_clock(admin, base, 20)
    assert state.projections[QUESTS][quest]["status"] == "READY"


def test_defeat_requires_unique_target_crossing_zero_and_cannot_farm_repeated_hits(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    resources(app, admin, base, card["entity_id"], hp=12, mana=8)
    resources(app, admin, base, target, hp=1)
    quest = configure_quest(
        admin,
        base,
        maker,
        [{"kind": "DEFEAT", "description": "Defeat two threats", "target_ids": [target, maker]}],
    )
    accepted(player, base, card, quest)
    advance_clock(admin, base, 6)
    first = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": target},
        "defeat",
    )
    assert first.status_code == 200, first.get_json()
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    assert state.projections[QUESTS][quest]["evidence"][0]["progress"] == 1
    # A later authorized revival and another genuine defeat still count that target once.
    resources(app, admin, base, target, hp=1)
    advance_clock(admin, base, 12)
    second = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": target},
        "defeat-again",
    )
    assert second.status_code == 200, second.get_json()
    row = state.projections[QUESTS][quest]
    assert row["status"] == "ACTIVE" and row["evidence"][0]["progress"] == 1


@pytest.mark.parametrize("kind", [ActorKind.HUMAN, ActorKind.AGENT])
def test_human_and_agent_trial_use_same_quest_evidence_and_once_only_rewards(kind):
    domain = domain_fixture.__wrapped__()
    actor = domain["actor"].model_copy(update={"kind": kind})
    domain["state"].projections["tabletop.entities"][str(domain["merchant"])].update(x=2, y=2)
    config = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.quest.configure",
            {
                "giver_id": str(domain["merchant"]),
                "title": "Road",
                "description": "Walk to the road",
                "objectives": [{"kind": "MOVE", "description": "Reach road", "x": 2, "y": 1}],
                "reward_gold": 7,
            },
            "offer",
        ),
        actor,
    )
    identity = config.result.result["quest_id"]
    domain["bus"].execute(
        proposal(domain, "tabletop.quest.accept", {"quest_id": identity}, "accept"), actor
    )
    domain["bus"].execute(
        proposal(domain, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "walk"), actor
    )
    request = proposal(domain, "tabletop.quest.claim", {"quest_id": identity}, "reward")
    paid = domain["bus"].execute(request, actor)
    assert paid.result.result["status"] == "CLAIMED"
    assert domain["bus"].execute(request, actor) == paid
    assert domain["state"].projections["tabletop.entities"][str(domain["hero"])]["gold"] == 57
    assert domain["state"].projections["tabletop.entities"][str(domain["merchant"])]["gold"] == 93


def test_cancel_returns_funded_reserve_once_and_prevents_later_payout(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app)
    admin, player, card, path, run, target, base = game
    accepted(player, base, card, quest)
    completed(admin, player, base, card, buy)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    receipt = api_command(admin, base, "tabletop.quest.cancel", {"quest_id": quest}, "cancel")
    giver = state.projections["tabletop.entities"][maker]
    assert giver["gold"] == 95 and giver["inventory"]["food"] == 2
    mark = state.version, state.state_hash
    assert (
        api_command(admin, base, "tabletop.quest.cancel", {"quest_id": quest}, "cancel") == receipt
    )
    assert (state.version, state.state_hash) == mark
    advance_clock(admin, base, 13)
    mark = state.version, state.state_hash
    for kind, client, card_or_none in [
        ("tabletop.quest.claim", player, card),
        ("tabletop.quest.cancel", admin, None),
        ("tabletop.quest.accept", player, card),
    ]:
        response = client.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": kind,
                "parameters": {"quest_id": quest},
                "idempotency_key": "settled-" + kind,
                **({"embodied_entity_id": card_or_none["entity_id"]} if card_or_none else {}),
            },
        )
        assert response.status_code == 400 and (state.version, state.state_hash) == mark


@pytest.mark.parametrize("fault", ["funds", "items", "foreign_target", "player_manager"])
def test_unfunded_or_unauthorized_definition_leaves_no_reserve_or_ledger_writes(
    monkeypatch, tmp_path, fault
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, base = game
    parameters = {
        "giver_id": maker,
        "title": "Errand",
        "description": "Help nearby",
        "objectives": [{"kind": "WEED", "description": "Weed", "units": 1}],
        "reward_gold": 1,
        "reward_items": {"food": 1},
    }
    if fault == "funds":
        parameters["reward_gold"] = 1000
    elif fault == "items":
        parameters["reward_items"] = {"food": 1, "missing": 1}
    elif fault == "foreign_target":
        parameters["objectives"] = [
            {"kind": "DEFEAT", "description": "Defeat", "target_ids": [str(uuid.uuid4())]}
        ]
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    mark = state.version, state.state_hash
    response = (player if fault == "player_manager" else admin).post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.quest.configure",
            "parameters": parameters,
            "idempotency_key": "bad-definition",
        },
    )
    assert response.status_code == (403 if fault == "player_manager" else 400)
    assert (state.version, state.state_hash) == mark


@pytest.mark.parametrize("fault", ["giver_dead", "giver_far", "giver_hidden", "wrong_owner"])
def test_ready_reward_needs_correct_owner_and_physically_available_giver(
    monkeypatch, tmp_path, fault
):
    app = _app(monkeypatch, tmp_path)
    game, maker, buy, sell, quest = prepare_quest(app)
    admin, player, card, path, run, target, base = game
    accepted(player, base, card, quest)
    completed(admin, player, base, card, buy)
    advance_clock(admin, base, 13)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    if fault == "giver_dead":
        state.projections["tabletop.entities"][maker].update(hp=0, dead=True)
    elif fault == "giver_far":
        state.projections["tabletop.entities"][maker]["x"] = 20
        state.projections.get("tabletop.spatial.positions", {}).get(maker, {})["x"] = 20
    elif fault == "giver_hidden":
        state.projections.setdefault("tabletop.sensory_profiles", {})[maker] = {"invisible": True}
    mark = state.version, state.state_hash
    actor = {"entity_id": target} if fault == "wrong_owner" else card
    response = command(
        admin if fault == "wrong_owner" else player,
        base,
        actor,
        "tabletop.quest.claim",
        {"quest_id": quest},
        "bad-reward",
    )
    assert response.status_code == 400 and (state.version, state.state_hash) == mark
