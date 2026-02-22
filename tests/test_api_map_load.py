import pytest

from app import app

pytestmark = pytest.mark.unit


def test_campaign_maps_endpoint_returns_demo_map(monkeypatch):
    def fake_execute_query(_query, _params):
        return [{"id": "44444444-4444-4444-4444-444444444441", "name": "Eclipse Keep Ground Floor"}]

    monkeypatch.setattr("shared.db.connection.execute_query", fake_execute_query)

    with app.test_client() as client:
        response = client.get("/api/campaigns/11111111-1111-1111-1111-111111111111/maps")

    assert response.status_code == 200
    assert response.get_json()[0]["name"] == "Eclipse Keep Ground Floor"


def test_map_detail_endpoint_returns_nodes(monkeypatch):
    monkeypatch.setattr(
        "services.domain.maps.system.MapSystem.get_map_data",
        lambda self, _map_id: {
            "map": {"id": "44444444-4444-4444-4444-444444444441", "name": "Eclipse Keep Ground Floor"},
            "nodes": [{"x": 5, "y": 5}, {"x": 6, "y": 5}],
        },
    )

    with app.test_client() as client:
        response = client.get("/api/maps/44444444-4444-4444-4444-444444444441")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["map"]["name"] == "Eclipse Keep Ground Floor"
    assert len(payload["nodes"]) == 2
