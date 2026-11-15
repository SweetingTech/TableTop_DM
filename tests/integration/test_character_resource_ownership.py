from __future__ import annotations

import uuid

import psycopg2
import pytest

from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_tactical_choices import resources

pytestmark = pytest.mark.integration


def test_bound_card_rejects_resource_edits_atomically_after_restart(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"], hp=3, mana=4)
    before = durable_mark(integration_stack, base)
    endpoint = f"/api/v2/player/characters/{card['character_id']}"
    restored, client = player_after_restart(tmp_path, player)
    for field, value in [
        ("status", "DEAD"),
        ("current_hit_points", 12),
        ("maximum_hit_points", 20),
        ("armor_class", 30),
        ("speed", 99),
        ("world_id", "00000000-0000-0000-0000-000000000001"),
    ]:
        response = client.patch(endpoint, json={field: value, "name": "Must not partially update"})
        assert response.status_code == 400, response.get_json()
        saved = next(
            row
            for row in client.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert saved == card
        assert durable_mark(integration_stack, base) == before
    with psycopg2.connect(integration_stack.admin_url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT current_hit_points,status,name FROM tabletop.characters WHERE id=%s",
            (card["character_id"],),
        )
        assert cursor.fetchone() == (card["current_hit_points"], card["status"], card["name"])
    live = client.get(endpoint + "/live-state").get_json()
    assert live["body"]["hp"] == 3 and live["body"]["mana"] == 4
    for world in (card["world_id"].upper(), uuid.UUID(card["world_id"]).hex):
        edited = client.patch(endpoint, json={"world_id": world, "name": "Same durable world"})
        assert edited.status_code == 200, edited.get_json()
        assert edited.get_json()["world_id"] == card["world_id"]
        assert edited.get_json()["entity_id"] == card["entity_id"]
        assert durable_mark(integration_stack, base) == before
