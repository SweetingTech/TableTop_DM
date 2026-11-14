from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_world_time import api_command, clock_game

pytestmark = pytest.mark.e2e


def test_returning_player_sees_routine_work_and_meal_without_private_lifecycle(
    browser, monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    root, member_path, bind_body = seed_routine(app, admin, base, target)
    for due, rain in ((30, True), (90, False)):
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
        {"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 40},
        "forty",
    )
    with serve_game(app, player, browser) as page:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        expect(page.get_by_text("Weeding · 25% · waiting · work 30", exact=True)).to_be_visible()
        assert (
            admin.post(
                member_path + "/activate", json={"active_state": {}, "world_step": 40}
            ).status_code
            == 200
        )
        assert admin.post(member_path + "/deactivate", json={"world_step": 40}).status_code == 200
        api_command(
            admin,
            base,
            "tabletop.clock.advance",
            {"expected_epoch": 1, "expected_seconds": 40, "to_seconds": 100},
            "hundred",
        )
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Weeding · 33% · running · work 40", exact=True)).to_be_visible()
        api_command(
            admin,
            base,
            "tabletop.clock.advance",
            {"expected_epoch": 1, "expected_seconds": 100, "to_seconds": 310},
            "hungry",
        )
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Eating · 0% · waiting · work 180", exact=True)).to_be_visible()
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            rendered = page.locator("body").inner_text()
            assert "PRIVATE_GARDEN_HISTORY" not in rendered and "MATERIALIZED" not in rendered
        assert not errors
