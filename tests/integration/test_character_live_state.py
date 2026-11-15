from __future__ import annotations

import psycopg2
import pytest

from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_tactical_choices import command, resources

pytestmark = pytest.mark.integration


def test_live_character_state_restarts_without_card_sync_or_read_mutations(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    resources(app, admin, base, card["entity_id"], hp=5, mana=8)
    response = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {
            "spell_id": "MEND",
            "target_id": card["entity_id"],
        },
        "heal-before-live-read",
    )
    assert response.status_code == 200, response.get_json()
    mark = durable_mark(integration_stack, base)
    endpoint = f"/api/v2/player/characters/{card['character_id']}/live-state"
    view = player.get(endpoint)
    assert view.status_code == 200, view.get_json()
    assert view.headers["Cache-Control"] == "no-store"
    assert view.get_json()["source"] == "KERNEL"
    assert view.get_json()["body"]["hp"] == 9 and view.get_json()["body"]["mana"] == 6
    assert view.get_json()["body"]["branch_id"] == base["branch_id"]
    assert view.get_json()["card_version"] == card["card_version"]
    restored, client = player_after_restart(tmp_path, player)
    assert client.get(endpoint).get_json() == view.get_json()
    assert durable_mark(integration_stack, base) == mark
    with psycopg2.connect(integration_stack.admin_url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT current_hit_points FROM tabletop.characters WHERE id=%s",
            (card["character_id"],),
        )
        assert cursor.fetchone()[0] == card["current_hit_points"]
    # Ownership of an authored card alone does not survive revoked world authority.
    response = admin.put(
        f"/api/v2/admin/users/{card['owner_user_id']}/worlds/{base['world_id']}/roles",
        json={"roles": []},
    )
    assert response.status_code == 200
    revoked = client.get(endpoint)
    assert revoked.status_code == 403 and revoked.headers["Cache-Control"] == "no-store"
    assert durable_mark(integration_stack, base) == mark
