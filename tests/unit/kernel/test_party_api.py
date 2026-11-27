from __future__ import annotations

import uuid

import pytest

from domains.tabletop.parties import INVITATIONS, PARTIES
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import clock_game

pytestmark = pytest.mark.unit


def party_command(client, base, body_id, action, parameters, key):
    return command(
        client, base, {"entity_id": body_id}, f"tabletop.party.{action}", parameters, key
    )


def party_result(response):
    assert response.status_code == 200, response.get_json()
    return response.get_json()["result"]["result"]


def create_and_invite(game):
    admin, player, card, _, _, target, base = game
    created = party_command(
        player,
        base,
        card["entity_id"],
        "create",
        {"name": "River Wardens", "goal": "Keep the ferry crossing safe."},
        "form-party",
    )
    party_id = party_result(created)["party_id"]
    assert all(delta["projection"] != PARTIES for delta in created.get_json()["result"]["deltas"])
    advance_clock(admin, base, 6)
    invited = party_command(
        player,
        base,
        card["entity_id"],
        "invite",
        {"party_id": party_id, "invitee_id": target},
        "invite-resident",
    )
    invitation_id = party_result(invited)["invitation_id"]
    assert invitation_id == invited.get_json()["event"]["event_id"]
    assert all(
        delta["projection"] != INVITATIONS for delta in invited.get_json()["result"]["deltas"]
    )
    return party_id, invitation_id


def party_scene(client, path):
    response = client.get(path + "/scene")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


@pytest.mark.parametrize("hostile", [False, True])
def test_resident_can_decline_join_leave_and_rejoin_without_body_access(
    monkeypatch, tmp_path, hostile
):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, _, resident, base = game
    founder = card["entity_id"]
    resident_path = path.removesuffix(founder) + resident
    party_id, invite_id = create_and_invite(game)
    response = {"invitation_id": invite_id, "accept": True}
    scene = party_scene(player, path)
    assert scene["party_invitations"] == []
    assert scene["parties"][0]["member_ids"] == [founder]
    invited = party_scene(admin, resident_path)
    assert invited["parties"] == []
    assert invited["party_invitations"][0]["goal"] == "Keep the ferry crossing safe."
    assert player.get(resident_path + "/scene").status_code == 403
    assert (
        party_command(player, base, resident, "respond", response, "steal-body").status_code == 403
    )

    declined = party_command(
        admin, base, resident, "respond", {**response, "accept": False}, "decline"
    )
    assert party_result(declined)["kind"] == "DECLINED"
    advance_clock(admin, base, 12)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = state.state_hash, state.version
    assert (
        party_command(admin, base, resident, "respond", response, "ignore-decline").status_code
        == 400
    )
    assert (state.state_hash, state.version) == before

    invite_fields = {"party_id": party_id, "invitee_id": resident}
    offered = party_command(player, base, founder, "invite", invite_fields, "second-invite")
    response["invitation_id"] = party_result(offered)["invitation_id"]
    joined = party_command(admin, base, resident, "respond", response, "accept")
    assert party_result(joined)["kind"] == "JOINED"
    assert party_scene(player, path)["parties"][0]["member_ids"] == [founder, resident]
    assert party_scene(admin, resident_path)["party_invitations"] == []
    assert player.get(resident_path + "/scene").status_code == 403

    advance_clock(admin, base, 18)
    left = party_command(
        admin,
        base,
        resident,
        "leave",
        {"party_id": party_id, "reason": "I promised to help my sister.", "hostile": hostile},
        "leave",
    )
    departure = party_result(left)
    assert departure["kind"] == ("HOSTILE_EXIT" if hostile else "LEFT")
    assert departure["reason"] == "I promised to help my sister."
    scene = party_scene(player, path)
    assert scene["parties"][0]["member_ids"] == [founder]
    assert "help my sister" not in str(scene)
    assert party_scene(admin, resident_path)["parties"] == []

    offered = party_command(player, base, founder, "invite", invite_fields, "third-invite")
    response["invitation_id"] = party_result(offered)["invitation_id"]
    advance_clock(admin, base, 24)
    reunion = party_command(admin, base, resident, "respond", response, "reunion")
    reunion_event = party_result(reunion)
    assert reunion_event["kind"] == "REUNITED"
    assert reunion_event["invitation_id"] == response["invitation_id"]
    assert reunion_event["prior_departure_event_id"] == left.get_json()["event"]["event_id"]
    assert (
        party_command(admin, base, resident, "respond", response, "reunion").get_json()["event"]
        == reunion.get_json()["event"]
    )


def test_invitation_id_cannot_be_used_from_a_different_body(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, _, _, _, base = game
    _, invite_id = create_and_invite(game)
    advance_clock(admin, base, 12)
    result = party_command(
        player,
        base,
        card["entity_id"],
        "respond",
        {"invitation_id": invite_id, "accept": True},
        "take-invite",
    )
    assert result.status_code == 400
