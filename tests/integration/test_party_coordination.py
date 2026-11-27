from __future__ import annotations

import pytest

from tests.integration.test_action_rules import player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_party_api import party_scene
from tests.unit.kernel.test_party_coordination import autonomous_waypoint, exchange_at_cache

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("flow", ["travel", "cache"])
def test_party_coordination_survives_restart(integration_stack, monkeypatch, tmp_path, flow):
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    _, player, _, path, _, _, base = game
    if flow == "travel":
        autonomous_waypoint(app, game)
    else:
        exchange_at_cache(app, game)
    before = party_scene(player, path)["parties"]
    _, restored = player_after_restart(tmp_path, player)
    assert party_scene(restored, path)["parties"] == before
    _, admin = fresh_client(tmp_path)
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
