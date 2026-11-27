from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest

from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_derived_combat_api import grant_items
from tests.unit.kernel.test_npc_goals import clock_path
from tests.unit.kernel.test_party_api import (
    create_and_invite,
    party_command,
    party_result,
    party_scene,
)
from tests.unit.kernel.test_party_runtime import assert_resident_response, prepare_invited_resident
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import NOW, clock_game

pytestmark = pytest.mark.unit


def joined_party(game):
    admin, _, _, _, _, resident, base = game
    party_id, invite_id = create_and_invite(game)
    joined = party_command(
        admin, base, resident, "respond", {"invitation_id": invite_id, "accept": True}, "join"
    )
    assert party_result(joined)["kind"] == "JOINED"
    advance_clock(admin, base, 12)
    return party_id


def position_in(scene, body):
    return next(row["position"] for row in scene["perceived_entities"] if row["entity_id"] == body)


def test_leadership_and_travel_are_separate_from_body_authority(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, _, resident, base = game
    founder = card["entity_id"]
    party_id = joined_party(game)
    plan = {"party_id": party_id, "goal": "Reach the north bank", "waypoint": {"x": 1, "y": 2}}
    assert party_command(admin, base, resident, "plan", plan, "outsider-plan").status_code == 400
    issued = party_command(player, base, founder, "plan", plan, "river-plan")
    assert party_result(issued)["kind"] == "PLAN_UPDATED"
    event_id = issued.get_json()["event"]["event_id"]
    request = {"party_id": party_id, "plan_event_id": event_id, "follow": True}
    assert (
        party_command(player, base, resident, "follow", request, "force-follow").status_code == 403
    )
    assert (
        party_result(party_command(admin, base, resident, "follow", request, "agree"))["kind"]
        == "FOLLOWING"
    )
    scene = party_scene(player, path)
    assert position_in(scene, resident)["y"] == 0
    assert scene["parties"][0]["following_member_ids"] == [resident]

    advance_clock(admin, base, 18)
    moved = command(
        admin,
        base,
        {"entity_id": resident},
        "tabletop.spatial.move",
        {"dx": 0, "dy": 1},
        "resident-step",
    )
    assert moved.status_code == 200, moved.get_json()
    transferred = party_command(
        player,
        base,
        founder,
        "transfer_leadership",
        {
            "party_id": party_id,
            "successor_id": resident,
        },
        "pass-lead",
    )
    assert party_result(transferred)["kind"] == "LEADER_CHANGED"
    advance_clock(admin, base, 24)
    assert party_command(player, base, founder, "plan", plan, "former-leader").status_code == 400
    assert (
        party_result(party_command(admin, base, resident, "plan", plan, "new-plan"))["kind"]
        == "PLAN_UPDATED"
    )
    stale = party_command(player, base, founder, "follow", request, "stale-follow")
    assert stale.status_code == 400
    scene = party_scene(player, path)
    assert scene["parties"][0]["leader_id"] == resident
    assert scene["parties"][0]["following_member_ids"] == []
    assert position_in(scene, founder)["y"] == 0
    assert position_in(scene, resident)["y"] == 1
    assert player.get(path.removesuffix(founder) + resident + "/scene").status_code == 403


def exchange_at_cache(app, game):
    admin, player, card, path, _, resident, base = game
    founder = card["entity_id"]
    grant_items(app, admin, base, founder)
    party_id = joined_party(game)
    donated = {"party_id": party_id, "direction": "DEPOSIT", "item": "SPEAR", "amount": 1}
    deposit = party_command(player, base, founder, "supplies", donated, "donate-spear")
    assert party_result(deposit)["kind"] == "SUPPLIES_MOVED"
    assert all(
        delta["projection"] != "tabletop.parties"
        for delta in deposit.get_json()["result"]["deltas"]
    )
    supplies = party_scene(player, path)["parties"][0]["supplies"]
    assert supplies["inventory"] == {"SPEAR": 1}
    take = {**donated, "direction": "WITHDRAW"}
    assert (
        party_command(admin, base, resident, "supplies", take, "remote-withdraw").status_code == 400
    )
    moved = command(
        admin,
        base,
        {"entity_id": resident},
        "tabletop.spatial.move",
        {"dx": -1, "dy": 0},
        "to-cache",
    )
    assert moved.status_code == 200, moved.get_json()
    advance_clock(admin, base, 18)
    withdrawn = party_command(admin, base, resident, "supplies", take, "withdraw-at-cache")
    assert party_result(withdrawn)["kind"] == "SUPPLIES_MOVED"
    assert party_scene(player, path)["parties"][0]["supplies"] is None
    snapshot = app.extensions["world_runner"].snapshot()
    bodies = snapshot.states.get(uuid.UUID(base["branch_id"])).projections["tabletop.entities"]
    assert bodies[founder]["inventory"]["SPEAR"] == 0
    assert bodies[resident]["inventory"]["SPEAR"] == 1
    return withdrawn.get_json()


def test_party_can_only_exchange_contributed_inventory_at_the_cache(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    exchange_at_cache(app, clock_game(app))


def test_hearing_does_not_follow_party_membership(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, _, resident, base = game
    party_id = joined_party(game)
    resident_path = path.removesuffix(card["entity_id"]) + resident
    heard = command(
        player,
        base,
        card,
        "tabletop.dialogue.speak",
        {"text": "Meet at the ferry.", "volume": "WHISPER"},
        "heard",
    )
    assert heard.status_code == 200, heard.get_json()
    assert "Meet at the ferry." in str(party_scene(admin, resident_path)["recent_observations"])
    moved = command(
        admin,
        base,
        {"entity_id": resident},
        "tabletop.spatial.move",
        {"dx": 1, "dy": 0},
        "outside-whisper-range",
    )
    assert moved.status_code == 200, moved.get_json()
    missed = command(
        player,
        base,
        card,
        "tabletop.dialogue.speak",
        {"text": "The ferryman knows a secret.", "volume": "WHISPER"},
        "missed",
    )
    assert missed.status_code == 200, missed.get_json()
    scene = party_scene(admin, resident_path)
    assert scene["parties"][0]["party_id"] == party_id
    assert "The ferryman knows a secret." not in str(scene["recent_observations"])


def autonomous_waypoint(app, game=None, *, human_owner=False):
    game, resident_path, party_id, invite_id = prepare_invited_resident(
        app, game, max_steps=3, human_owner=human_owner
    )
    admin, player, card, player_path, _, resident, base = game
    assert_resident_response(app, base, resident, invite_id, accept=True)
    clock = app.extensions["world_runner"]
    assert clock.run_once(NOW + timedelta(seconds=6)) >= 1
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 12
    plan = {"party_id": party_id, "goal": "Help tend the north bank", "waypoint": {"x": 1, "y": 2}}
    assert (
        party_result(party_command(player, base, card["entity_id"], "plan", plan, "waypoint"))[
            "kind"
        ]
        == "PLAN_UPDATED"
    )
    runner = app.extensions["character_runner"]

    def run_ready_step():
        deadline = time.monotonic() + 3
        while not runner.controllers.due() and time.monotonic() < deadline:
            time.sleep(0.025)
        assert runner.run_once() == 1

    run_ready_step()
    assert party_scene(admin, resident_path)["parties"][0]["following_member_ids"] == [resident]
    assert clock.run_once(NOW + timedelta(seconds=12)) >= 1
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 18
    run_ready_step()
    branch = uuid.UUID(base["branch_id"])
    action = runner.snapshot().command_history[branch][-1]
    assert action.proposal.command_type == "tabletop.spatial.move"
    assert str(action.proposal.embodied_entity_id) == resident
    assert action.result.result["destination"] == {"x": 1, "y": 1}
    assert position_in(party_scene(player, player_path), card["entity_id"])["y"] == 0
    return game


def test_resident_chooses_to_follow_and_walks_their_own_step(monkeypatch, tmp_path):
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    autonomous_waypoint(_app(monkeypatch, tmp_path))
