from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_world_time import api_command, clock_game

pytestmark = pytest.mark.e2e


def test_returning_player_sees_offscreen_partial_work_and_rain_wait(browser, monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    for due, rain in ((3, True), (7, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"due_seconds": due, "zone_id": "world", "raining": rain},
            f"rain{due}",
        )
    api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 5},
        "five",
    )
    with serve_game(app, player, browser) as page:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        expect(page.get_by_text("Weeding · 3% · waiting · work 3", exact=True)).to_be_visible()
        api_command(
            admin,
            base,
            "tabletop.clock.advance",
            {"expected_epoch": 1, "expected_seconds": 5, "to_seconds": 10},
            "ten",
        )
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Weeding · 6% · running · work 6", exact=True)).to_be_visible()
        assert "executor_actor_id" not in page.locator("body").inner_text()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors
