import pytest

from app import app

pytestmark = pytest.mark.integration

CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
MAP_ID = "44444444-4444-4444-4444-444444444441"


def test_seeded_demo_map_loads_for_campaign(integration_stack) -> None:
    del integration_stack

    with app.test_client() as client:
        maps_response = client.get(f"/api/campaigns/{CAMPAIGN_ID}/maps")
        assert maps_response.status_code == 200
        maps = maps_response.get_json()
        assert any(m["id"] == MAP_ID for m in maps)

        detail_response = client.get(f"/api/maps/{MAP_ID}")
        assert detail_response.status_code == 200
        payload = detail_response.get_json()
        assert payload["map"]["id"] == MAP_ID
        assert len(payload["nodes"]) >= 1
