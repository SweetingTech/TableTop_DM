from __future__ import annotations

import pytest

from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_quest_transfer_api import crossing, resident_campaign
from tests.unit.kernel.test_tactical_choices import command

pytestmark = pytest.mark.integration


def test_transferred_opportunity_replays_and_retry_cannot_pay_twice(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, quest, paid = crossing(app, game)
    _, _, _, _, _, resident, base = game
    mark = durable_mark(integration_stack, base)
    _, admin = fresh_client(tmp_path)
    retry = command(
        admin,
        base,
        {"entity_id": resident},
        "tabletop.quest.claim",
        {
            "quest_id": quest,
        },
        "warden-reward",
    )
    assert retry.status_code == 200, retry.get_json()
    assert retry.get_json()["event"] == paid["event"]
    assert durable_mark(integration_stack, base) == mark
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_resident_campaign_crosses_control_restart_and_replay(
    integration_stack, monkeypatch, tmp_path
):
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    game, _ = resident_campaign(
        app, game, reconnect=lambda player: player_after_restart(tmp_path, player)
    )
    admin, _, _, _, _, _, base = game
    replay = admin.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]
