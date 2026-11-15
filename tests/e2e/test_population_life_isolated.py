from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_world_time import api_command, clock_game
from tests.unit.population.test_life import configure_game_life, game_meeting

pytestmark = pytest.mark.e2e


def test_player_observes_travel_sleep_and_social_activity_without_private_plans(
    browser, monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, run, target, base = game
    configure_game_life(app, game)
    partner, identity = game_meeting(admin, base, target)
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.spatial.move",
            "idempotency_key": "look-closer",
            "parameters": {"dx": 1, "dy": 0},
        },
    )
    assert response.status_code == 200
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 70},
        "travel",
    )
    with serve_game(app, player, browser) as page:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        expect(page.get_by_text("Traveling · running · work 60", exact=True)).to_be_visible()
        api_command(
            admin,
            base,
            "tabletop.clock.advance",
            {"expected_epoch": 1, "expected_seconds": 70, "to_seconds": 90},
            "sleep",
        )
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Sleeping · running · work 60", exact=True)).to_be_visible()
        api_command(
            admin,
            base,
            "tabletop.clock.advance",
            {"expected_epoch": 1, "expected_seconds": 90, "to_seconds": 210},
            "meeting",
        )
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Socializing · running · work 70", exact=True)).to_be_visible()
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            text = page.locator("body").inner_text()
            for hidden in (
                identity,
                "starts_seconds",
                "workplace",
                "awake_until",
                "PRIVATE_GARDEN_HISTORY",
            ):
                assert hidden not in text
        assert not errors
