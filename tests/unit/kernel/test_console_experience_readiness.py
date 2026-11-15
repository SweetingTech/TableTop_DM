from __future__ import annotations

import uuid

import pytest

from domains.tabletop.spatial.scene import PerceivedScene
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def test_human_scene_waits_for_other_bodys_observation_projection_without_changing_cognition(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app)
    ids = app.extensions["demo_ids"]
    body = str(uuid.uuid4())
    common = {"world_id": card["world_id"], "branch_id": str(ids["branch_id"]), "run_id": run}
    assert (
        admin.post(
            "/api/v2/commands",
            json={
                **common,
                "command_type": "tabletop.entity.spawn",
                "parameters": {
                    "entity_id": body,
                    "name": "Nearby walker",
                    "entity_type": "NPC",
                    "controller_actor_id": str(ids["actor_id"]),
                    "public_state": {"x": 1, "y": 0, "zone_id": "world"},
                },
                "idempotency_key": "nearby-walker",
            },
        ).status_code
        == 200
    )
    simulation = app.extensions["simulation"]
    projector = simulation.subjective_projector
    pending = []
    simulation.configure_subjective_projector(pending.append)
    assert (
        admin.post(
            "/api/v2/commands",
            json={
                **common,
                "command_type": "tabletop.spatial.move",
                "embodied_entity_id": body,
                "parameters": {"dx": 1, "dy": 0},
                "idempotency_key": "nearby-step",
            },
        ).status_code
        == 200
    )
    before = player.get(path + "/scene").get_json()
    assert before["experience_ready"] is False
    assert "experience_ready" not in PerceivedScene.model_validate(before).model_dump()
    assert projector is not None
    for receipt in pending:
        projector(receipt)
    assert player.get(path + "/scene").get_json()["experience_ready"] is True
