from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene

pytestmark = pytest.mark.unit


def intent(base, card, key="trusted-entrypoint"):
    return {
        **base,
        "mode": "CHARACTER",
        "embodied_entity_id": card["entity_id"],
        "idempotency_key": key,
    }


def test_cognition_character_mode_shares_trusted_builder_and_receipt_with_scoped_route(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    sim = app.extensions["simulation"]
    state = sim.states.get(uuid.UUID(base["branch_id"]))
    before = (state.state_hash, state.version, len(sim.events))
    response = player.post("/api/v2/cognition/decide", json=intent(base, card))
    assert response.status_code == 200, response.get_json()
    assert response.headers["Cache-Control"] == "no-store"
    receipt = response.get_json()
    assert receipt["execution_mode"] == "PROPOSAL_ONLY" and receipt["committed"] is False
    assert receipt["scope"]["entity_id"] == card["entity_id"]
    assert (
        player.post(
            path + "/character-proposals",
            json={
                "run_id": run,
                "idempotency_key": "trusted-entrypoint",
            },
        ).get_json()
        == receipt
    )
    assert (state.state_hash, state.version, len(sim.events)) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("situation", {"hidden_plot": "INJECTED_DIRECTOR_SECRET"}),
        ("actions", [{"action": "Kill the hidden quest giver"}]),
        ("seed", 1),
        ("actor_id", str(uuid.uuid4())),
        ("persona_id", str(uuid.uuid4())),
        ("allow_llm", True),
        ("planning_goal", {"win": True}),
    ],
)
def test_character_mode_rejects_caller_context_policy_and_identity_overrides(
    monkeypatch, tmp_path, field, value
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    response = player.post("/api/v2/cognition/decide", json={**intent(base, card), field: value})
    assert response.status_code == 400, response.get_json()
    assert "INJECTED_DIRECTOR_SECRET" not in response.get_data(as_text=True)


def test_character_mode_validates_run_lineage_and_control(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    request = intent(base, card)
    assert (
        player.post(
            "/api/v2/cognition/decide",
            json={
                **request,
                "embodied_entity_id": target,
            },
        ).status_code
        == 403
    )
    assert player.post(
        "/api/v2/cognition/decide",
        json={
            **request,
            "run_id": str(uuid.uuid4()),
        },
    ).status_code in {400, 403}
    # Caller-authored evaluation remains privileged, even for a character owner.
    assert (
        player.post(
            "/api/v2/cognition/decide",
            json={
                "persona_id": str(uuid.uuid4()),
                "seed": 1,
                "actions": [],
            },
        ).status_code
        == 403
    )
