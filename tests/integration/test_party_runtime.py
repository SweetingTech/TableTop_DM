from __future__ import annotations

import pytest

from tests.integration.test_action_rules import player_after_restart
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_party_api import party_scene
from tests.unit.kernel.test_party_runtime import assert_resident_response, prepare_invited_resident

pytestmark = pytest.mark.integration


def test_resident_uses_pinned_motive_after_runner_restart(integration_stack, monkeypatch, tmp_path):
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, resident_path, party_id, invite_id = prepare_invited_resident(app, game)
    _, player, card, player_path, _, resident, base = game
    restarted, restored_player = player_after_restart(tmp_path, player)
    assert_resident_response(restarted, base, resident, invite_id, accept=True)
    party = party_scene(restored_player, player_path)["parties"][0]
    assert party["party_id"] == party_id
    assert party["member_ids"] == [card["entity_id"], resident]
    assert restored_player.get(resident_path + "/scene").status_code == 403
