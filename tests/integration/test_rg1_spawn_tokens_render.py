import pytest

from app import app

pytestmark = pytest.mark.integration

CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"


def test_seeded_tokens_include_render_coordinates(integration_stack) -> None:
    del integration_stack

    with app.test_client() as client:
        entities_resp = client.get(f"/api/campaigns/{CAMPAIGN_ID}/entities")
        assert entities_resp.status_code == 200
        entities = entities_resp.get_json()

    token_entities = [
        e
        for e in entities
        if e["entity_type"] in {"PC", "NPC"}
        and isinstance(e.get("public_sheet"), dict)
        and "x" in e["public_sheet"]
        and "y" in e["public_sheet"]
    ]

    assert len(token_entities) >= 3
