from __future__ import annotations

import uuid

import pytest

from domains.tabletop.quests.contracts import QUESTS
from domains.tabletop.recovery import save_roll
from kernel.randomness import allocate_randomness
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_derived_combat_api import grant_items
from tests.unit.kernel.test_npc_goals import clock_path
from tests.unit.kernel.test_party_api import party_command, party_result, party_scene
from tests.unit.kernel.test_party_coordination import autonomous_waypoint
from tests.unit.kernel.test_tactical_choices import command, resources
from tests.unit.kernel.test_world_time import NOW, api_command, clock_game

pytestmark = pytest.mark.unit


def state_of(app, base):
    return app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))


def spawn_contact(admin, base, identity, name, *, hp, x, y, gold=0):
    return api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": str(identity),
            "name": name,
            "entity_type": "NPC",
            "public_state": {"x": x, "y": y, "hp": hp, "max_hp": hp, "gold": gold},
        },
        name,
    )


def configure_opportunity(app, game, *, second_contact=True, transferable=True):
    admin, _, card, _, run, _, base = game
    informant = uuid.uuid5(uuid.UUID(run), "ford-warden")
    spawn_contact(admin, base, informant, "Ford warden", hp=12, x=1, y=1)
    resources(app, admin, base, card["entity_id"], hp=12, mana=8)
    snapshot = app.extensions["world_runner"].snapshot()
    branch = snapshot.states.get(uuid.UUID(base["branch_id"]))
    randomness = allocate_randomness(
        snapshot.runs[uuid.UUID(run)].seed, branch.version + 3, "tabletop.magic.invoke"
    )
    # Select a fixture body whose ordinary death saves finish in two clock rounds.
    for index in range(1024):
        giver = uuid.uuid5(uuid.UUID(run), f"quest-contact-{index}")
        if (
            save_roll(randomness.action_seed, giver, 0) == 1
            and save_roll(randomness.action_seed, giver, 1) < 10
        ):
            break
    else:
        raise AssertionError("no deterministic contact fixture was found")
    spawn_contact(admin, base, giver, "Bridge steward", hp=1, x=0, y=1, gold=20)
    configured = api_command(
        admin,
        base,
        "tabletop.quest.configure",
        {
            "giver_id": str(giver),
            "title": "Make the crossing safe",
            "description": "Check a route to the north bank.",
            "reward_gold": 7,
            "required_items": {"SPEAR": 1},
            "transferable": transferable,
            "alternate_giver_ids": [str(informant)] if second_contact else [],
            "objectives": [
                {"kind": "MOVE", "description": "Reach the north bank", "x": 20, "y": 20}
            ],
            "alternate_approaches": [
                {
                    "title": "Inspect the ford",
                    "objectives": [
                        {"kind": "MOVE", "description": "Reach the ford marker", "x": 1, "y": 0},
                    ],
                }
            ],
        },
        "fund-crossing-opportunity",
    )
    return (
        configured["result"]["result"]["quest_id"],
        str(giver),
        str(informant),
        randomness.action_seed,
    )


def lose_giver(app, game, giver, seed, seconds):
    admin, player, card, _, _, _, base = game
    hit = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {
            "spell_id": "ARCANE_BOLT",
            "target_id": giver,
        },
        "steward-defeated",
    )
    assert hit.status_code == 200, hit.get_json()
    assert hit.get_json()["result"]["result"]["randomness"]["action_seed"] == seed
    advance_clock(admin, base, seconds + 12)
    assert state_of(app, base).projections["tabletop.entities"][giver]["dead"]


def accept_and_complete(app, game, quest_id, giver, informant, *, now):
    admin, player, card, path, _, _, base = game
    quest = {"quest_id": quest_id}
    visible = {
        row["entity_id"]: row["quest_offers"]
        for row in party_scene(player, path)["perceived_entities"]
    }
    assert visible[giver] == []
    assert visible[informant][0]["quest_id"] == quest_id
    assert visible[informant][0]["required_items"] == {"SPEAR": 1}
    denied = command(player, base, card, "tabletop.quest.accept", quest, "missing-tool")
    assert denied.status_code == 400 and "required items" in denied.get_json()["details"]
    grant_items(app, admin, base, card["entity_id"])
    accepted = command(player, base, card, "tabletop.quest.accept", quest, "accept-from-warden")
    assert accepted.status_code == 200, accepted.get_json()
    assert informant not in str(accepted.get_json()["result"]["result"])
    advance_clock(admin, base, now + 6)
    moved = command(player, base, card, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "ford-marker")
    assert moved.status_code == 200, moved.get_json()
    recorded = state_of(app, base).projections[QUESTS][quest_id]
    assert recorded["status"] == "READY"
    assert recorded["evidence"][0]["progress"] == 0
    assert recorded["alternate_evidence"][0][0]["progress"] == 1
    return recorded["alternate_evidence"][0][0]["last_source_command_id"]


def transfer_crossing(
    app, game, *, now, quest_id, informant, recipient_client, recipient_base=None
):
    admin, player, card, path, _, resident, base = game
    resident_card = {"entity_id": resident}
    if recipient_base is None:
        recipient_base = base
    quest = {"quest_id": quest_id}
    resident_path = path.removesuffix(card["entity_id"]) + resident
    offered = command(
        player,
        base,
        card,
        "tabletop.quest.offer_transfer",
        {
            **quest,
            "recipient_id": resident,
        },
        "give-resident-opportunity",
    )
    assert offered.status_code == 200, offered.get_json()
    offer_id = offered.get_json()["event"]["event_id"]
    known = next(
        row
        for row in party_scene(recipient_client, resident_path)["perceived_entities"]
        if row["entity_id"] == card["entity_id"]
    )
    assert known["quest_offers"][0]["quest_id"] == quest_id
    advance_clock(admin, base, now + 6)
    denied = command(
        recipient_client, recipient_base, resident_card, "tabletop.quest.accept", quest, "no-tools"
    )
    assert denied.status_code == 400 and "required items" in denied.get_json()["details"]
    api_command(admin, base, "test.owned_items", {"entity_id": resident}, "resident-tools")
    response = command(
        recipient_client,
        recipient_base,
        resident_card,
        "tabletop.quest.accept",
        quest,
        "take-opportunity",
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["result"]["result"]
    assert payload["status"] == "READY" and payload["transfer_event_id"] == offer_id
    assert (
        all(delta["projection"] != QUESTS for delta in response.get_json()["result"]["deltas"])
        or recipient_client is admin
    )
    advance_clock(admin, base, now + 12)
    assert (
        command(player, base, card, "tabletop.quest.claim", quest, "old-holder").status_code == 400
    )
    bodies = state_of(app, base).projections["tabletop.entities"]
    resident_gold = int(bodies[resident].get("gold", 0))
    paid = command(
        recipient_client,
        recipient_base,
        resident_card,
        "tabletop.quest.claim",
        quest,
        "warden-reward",
    )
    assert paid.status_code == 200, paid.get_json()
    assert paid.get_json()["result"]["result"]["status"] == "CLAIMED"
    final = state_of(app, base).projections["tabletop.entities"]
    assert final[resident]["gold"] == resident_gold + 7
    assert final[informant].get("gold", 0) == 0
    return paid.get_json()


def crossing(app, game=None):
    game = game or clock_game(app)
    admin, _, _, _, _, resident, base = game
    quest, giver, informant, seed = configure_opportunity(app, game)
    lose_giver(app, game, giver, seed, 0)
    source = accept_and_complete(app, game, quest, giver, informant, now=12)
    advance_clock(admin, base, 24)
    paid = transfer_crossing(
        app, game, now=24, quest_id=quest, informant=informant, recipient_client=admin
    )
    state = state_of(app, base)
    completed = state.projections[QUESTS][quest]
    assert completed["owner_id"] == resident
    assert completed["alternate_evidence"][0][0]["last_source_command_id"] == source
    assert state.projections["tabletop.entities"][giver]["gold"] == 13
    return game, quest, paid


def test_offered_opportunity_survives_giver_death_and_transfers_once(monkeypatch, tmp_path):
    crossing(_app(monkeypatch, tmp_path))


def test_dead_givers_do_not_delegate_implicitly(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, _, _, base = game
    quest, giver, informant, seed = configure_opportunity(app, game, second_contact=False)
    lose_giver(app, game, giver, seed, 0)
    grant_items(app, admin, base, card["entity_id"])
    nearby = next(
        row
        for row in party_scene(player, path)["perceived_entities"]
        if row["entity_id"] == informant
    )
    assert not nearby["quest_offers"]
    denied = command(
        player, base, card, "tabletop.quest.accept", {"quest_id": quest}, "undesignated-contact"
    )
    assert denied.status_code == 400
    assert state_of(app, base).projections[QUESTS][quest]["status"] == "OFFERED"


def test_transfer_requires_the_opportunity_to_permit_it(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, _, _, resident, base = game
    quest, giver, informant, seed = configure_opportunity(app, game, transferable=False)
    lose_giver(app, game, giver, seed, 0)
    accept_and_complete(app, game, quest, giver, informant, now=12)
    advance_clock(admin, base, 24)
    denied = command(
        player,
        base,
        card,
        "tabletop.quest.offer_transfer",
        {
            "quest_id": quest,
            "recipient_id": resident,
        },
        "nontransferable-quest",
    )
    assert denied.status_code == 400
    assert state_of(app, base).projections[QUESTS][quest]["owner_id"] == card["entity_id"]


def resident_campaign(app, game=None, *, reconnect=None):
    game = autonomous_waypoint(app, game, human_owner=True)
    admin, player, card, path, run, resident, base = game
    resident_path = path.removesuffix(card["entity_id"]) + resident
    party = party_scene(player, resident_path)["parties"][0]
    assert resident in party["following_member_ids"]
    control = player.get(resident_path + "/control", query_string={"run_id": run}).get_json()[
        "control"
    ]
    assert control["mode"] == "PAUSED" and control["step"] == 3
    left = {"party_id": party["party_id"], "reason": "My brother needs me on the night watch."}
    denied = party_command(
        player,
        {**base, "control_epoch": control["epoch"]},
        resident,
        "leave",
        left,
        "premature-leave",
    )
    assert denied.status_code == 403
    takeover = player.post(
        resident_path + "/control",
        json={
            "run_id": run,
            "mode": "HUMAN",
            "expected_epoch": control["epoch"],
            "idempotency_key": "resident-manual-takeover",
        },
    )
    assert takeover.status_code == 200, takeover.get_json()
    resident_base = {**base, "control_epoch": takeover.get_json()["state"]["epoch"]}
    assert app.extensions["character_runner"].run_once() == 0
    clock = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": clock["epoch"],
            "executor_actor_id": clock["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": True,
        },
        "hold-after-travel",
    )
    advance_clock(admin, base, 24)
    departure = party_command(player, resident_base, resident, "leave", left, "resident-leaves")
    assert party_result(departure)["reason"] == left["reason"]
    assert party_scene(player, resident_path)["parties"] == []
    assert party_scene(player, path)["parties"][0]["member_ids"] == [card["entity_id"]]

    quest, giver, informant, seed = configure_opportunity(app, game)
    lose_giver(app, game, giver, seed, 24)
    source = accept_and_complete(app, game, quest, giver, informant, now=36)
    advance_clock(admin, base, 48)
    paid = transfer_crossing(
        app,
        game,
        now=48,
        quest_id=quest,
        informant=informant,
        recipient_client=player,
        recipient_base=resident_base,
    )
    assert (
        state_of(app, base).projections[QUESTS][quest]["alternate_evidence"][0][0][
            "last_source_command_id"
        ]
        == source
    )
    if reconnect is not None:
        restarted, restored = reconnect(player)
        retry = command(
            restored,
            resident_base,
            {"entity_id": resident},
            "tabletop.quest.claim",
            {"quest_id": quest},
            "warden-reward",
        )
        assert retry.status_code == 200 and retry.get_json()["event"] == paid["event"]
        assert state_of(restarted, base).projections[QUESTS][quest]["owner_id"] == resident
        assert party_scene(restored, resident_path)["parties"] == []
    return game, quest


def test_ordinary_resident_works_with_party_takes_control_leaves_and_carries_task(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    resident_campaign(_app(monkeypatch, tmp_path))
