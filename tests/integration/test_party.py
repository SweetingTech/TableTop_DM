from __future__ import annotations

import pytest

from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_party_api import (
    create_and_invite,
    party_command,
    party_result,
    party_scene,
)

pytestmark = pytest.mark.integration


def test_party_invitation_and_consent_survive_restart_and_replay(
    integration_stack, monkeypatch, tmp_path
):
    _, game = prepare(integration_stack, monkeypatch, tmp_path)
    _, player, card, path, _, resident, base = game
    party_id, invite_id = create_and_invite(game)
    _, restored_admin = fresh_client(tmp_path)
    resident_path = path.removesuffix(card["entity_id"]) + resident
    assert (
        party_scene(restored_admin, resident_path)["party_invitations"][0]["invitation_id"]
        == invite_id
    )

    parameters = {"invitation_id": invite_id, "accept": True}
    joined = party_command(restored_admin, base, resident, "respond", parameters, "accept")
    assert party_result(joined)["kind"] == "JOINED"
    mark = durable_mark(integration_stack, base)
    _, restarted_admin = fresh_client(tmp_path)
    retry = party_command(restarted_admin, base, resident, "respond", parameters, "accept")
    assert party_result(retry) == party_result(joined)
    assert retry.get_json()["state_hash"] == joined.get_json()["state_hash"]
    assert durable_mark(integration_stack, base) == mark

    _, restarted_player = player_after_restart(tmp_path, player)
    parties = party_scene(restarted_player, path)["parties"]
    assert parties[0]["party_id"] == party_id
    assert parties[0]["member_ids"] == [card["entity_id"], resident]
    assert restarted_player.get(resident_path + "/scene").status_code == 403
    replay = restarted_admin.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
