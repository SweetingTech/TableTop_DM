from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from domains.tabletop.spatial.presentation import MapPresentation
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "changes",
    [
        {"min_x": 3, "max_x": 2},
        {"image_path": "https://example.com/map.png"},
        {"image_path": "/static/../private.png"},
        {"secret_state": {"hidden": "value"}},
    ],
)
def test_map_contract_rejects_invalid_extents_remote_assets_and_hidden_fields(changes):
    with pytest.raises(ValidationError):
        MapPresentation.model_validate(
            {
                "zone_id": "world",
                "name": "Yard",
                "min_x": 0,
                "max_x": 9,
                "min_y": 0,
                "max_y": 9,
                **changes,
            }
        )


def test_only_perceived_zone_maps_reach_human_scene_and_never_character_context(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app)
    ids = app.extensions["demo_ids"]
    base = {
        "command_type": "tabletop.map.configure",
        "world_id": card["world_id"],
        "branch_id": str(ids["branch_id"]),
        "run_id": run,
    }
    parameters = {
        "zone_id": "world",
        "name": "Review yard",
        "min_x": -5,
        "max_x": 5,
        "min_y": -5,
        "max_y": 5,
        "image_path": "/static/v2/assets/harborport-map.png",
    }
    assert (
        player.post(
            "/api/v2/commands",
            json={**base, "parameters": parameters, "idempotency_key": "denied-map"},
        ).status_code
        == 403
    )
    for zone in ("world", "PRIVATE_SETPIECE"):
        response = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "parameters": {**parameters, "zone_id": zone},
                "idempotency_key": "map-" + zone,
            },
        )
        assert response.status_code == 200, response.get_json()
    response = player.get(path + "/scene")
    assert response.status_code == 200
    assert response.get_json()["map_presentations"] == [parameters]
    assert "PRIVATE_SETPIECE" not in response.get_data(as_text=True)
    context = player.get(path + "/context", query_string={"run_id": run})
    assert context.status_code == 200
    assert "/static/" not in context.get_data(as_text=True)
    assert "map_presentations" not in context.get_data(as_text=True)
    assert os.environ["TTDM_OPERATOR_TOKEN"] not in response.get_data(as_text=True)
