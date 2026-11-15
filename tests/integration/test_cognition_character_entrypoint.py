from __future__ import annotations

import pytest

from cognition.projector import WorldEventProjector
from tests.integration.test_action_rules import durable_mark, player_after_restart
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.kernel.test_cognition_character_entrypoint import intent

pytestmark = pytest.mark.integration


def test_trusted_cognition_receipt_shares_scope_and_survives_restart_without_world_mutation(
    integration_stack, monkeypatch, tmp_path
):
    app, (admin, player, card, path, run, target, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    before = durable_mark(integration_stack, base)
    response = player.post("/api/v2/cognition/decide", json=intent(base, card))
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["execution_mode"] == "PROPOSAL_ONLY"
    assert durable_mark(integration_stack, base) == before
    restored, client = player_after_restart(tmp_path, player)
    assert (
        client.post("/api/v2/cognition/decide", json=intent(base, card)).get_json()
        == response.get_json()
    )
    assert (
        client.post(
            path + "/character-proposals",
            json={
                "run_id": run,
                "idempotency_key": "trusted-entrypoint",
            },
        ).get_json()
        == response.get_json()
    )
    assert durable_mark(integration_stack, base) == before
    response = client.post(
        "/api/v2/cognition/decide",
        json={
            **intent(base, card, "no-injection"),
            "situation": {"plot": "DIRECTOR_SECRET"},
        },
    )
    assert response.status_code == 400
    assert "DIRECTOR_SECRET" not in response.get_data(as_text=True)
    assert durable_mark(integration_stack, base) == before
