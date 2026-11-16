from __future__ import annotations

import uuid

import pytest

from kernel.postgres_repository import PostgresCommandRepository
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_relationship_snapshot_repairs import fresh_client
from tests.integration.test_world_time import prepare
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_derived_combat_api import prepare_combat
from tests.unit.kernel.test_tactical_choices import command

pytestmark = pytest.mark.integration


def test_derived_stats_owned_gear_restart_late_retry_card_isolation_and_replay(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = prepare_combat(app, game)
    first = command(
        player, base, card, "tabletop.equipment.equip", {"weapon_id": "SHORTSWORD"}, "equip"
    )
    assert first.status_code == 200, first.get_json()
    advance_clock(admin, base, 6)
    restored, client = player_after_restart(tmp_path, player)
    view = client.get(f"/api/v2/player/characters/{card['character_id']}/live-state").get_json()[
        "body"
    ]
    assert view["ability_scores"]["dexterity"] == 20 and view["equipped_weapon"] == "SHORTSWORD"
    assert view["attack_bonus"] == 7 and view["damage_bonus"] == 5
    mark = durable_mark(integration_stack, base)
    retry = command(
        client, base, card, "tabletop.equipment.equip", {"weapon_id": "SHORTSWORD"}, "equip"
    )
    assert retry.status_code == 200
    for field in ("result", "event", "state_hash"):
        assert retry.get_json()[field] == first.get_json()[field]
    assert durable_mark(integration_stack, base) == mark
    attack = command(client, base, card, "tabletop.combat.attack", {"target_id": target}, "attack")
    assert attack.status_code == 200, attack.get_json()
    assert attack.get_json()["result"]["result"]["attack_bonus"] == 7
    saved = next(
        row
        for row in client.get("/api/v2/player/characters").get_json()["items"]
        if row["character_id"] == card["character_id"]
    )
    assert saved == card
    _, operator = fresh_client(tmp_path)
    replay = operator.get(f"/api/v2/branches/{base['branch_id']}/replay")
    assert replay.status_code == 200 and replay.get_json()["verified"]


def test_failed_equip_keeps_inventory_profile_cost_and_ledger_atomic(
    integration_stack, monkeypatch, tmp_path
):
    app, game = prepare(integration_stack, monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = prepare_combat(app, game)
    mark = durable_mark(integration_stack, base)
    branch = uuid.UUID(base["branch_id"])
    original = PostgresCommandRepository._insert_event

    def fail(cursor, event):
        original(cursor, event)
        raise ValueError("injected equipment publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(PostgresCommandRepository, "_insert_event", staticmethod(fail))
        response = command(
            player, base, card, "tabletop.equipment.equip", {"weapon_id": "SPEAR"}, "equip"
        )
        assert response.status_code == 400
    assert durable_mark(integration_stack, base) == mark
    restored, client = player_after_restart(tmp_path, player)
    before = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert (
        before.projections["tabletop.entities"][card["entity_id"]]["equipped_weapon"] == "UNARMED"
    )
    assert card["entity_id"] not in before.projections.get("tabletop.action_time", {})
    response = command(
        client, base, card, "tabletop.equipment.equip", {"weapon_id": "SPEAR"}, "equip"
    )
    assert response.status_code == 200, response.get_json()
    after = restored.extensions["world_runner"].snapshot().states.get(branch)
    assert after.projections["tabletop.action_time"][card["entity_id"]]["ready_seconds"] == 6
