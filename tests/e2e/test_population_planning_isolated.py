from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_world_time import api_command, clock_game
from tests.unit.population.test_planning import configure_game_plan

pytestmark = pytest.mark.e2e


def test_offscreen_daily_choices_and_shelter_are_visible_without_private_goals(
    browser, monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, run, target, base = game
    configure_game_plan(app, game)
    for due, raining in ((40, True), (100, False)):
        api_command(
            admin,
            base,
            "tabletop.weather.schedule",
            {"zone_id": "world", "due_seconds": due, "raining": raining},
            f"rain:{due}",
        )
    assert (
        player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": card["entity_id"],
                "command_type": "tabletop.spatial.move",
                "idempotency_key": "nearby",
                "parameters": {"dx": 1, "dy": 0},
            },
        ).status_code
        == 200
    )
    with serve_game(app, player, browser) as page:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for old, until, label in (
            (0, 50, "Traveling · running · work 40"),
            (50, 70, "Resting"),
            (70, 300, "Resting"),
        ):
            api_command(
                admin,
                base,
                "tabletop.clock.advance",
                {"expected_epoch": 1, "expected_seconds": old, "to_seconds": until},
                f"advance:{until}",
            )
            page.reload(wait_until="networkidle")
            if until == 50:
                expect(page.get_by_text(label, exact=True)).to_be_visible()
            else:
                expect(page.get_by_text(label, exact=False)).to_be_visible()
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            text = page.locator("body").inner_text()
            for hidden in (
                "private_garden_goal",
                "private_reading_goal",
                "decision_sequence",
                "seconds_per_day",
                "PRIVATE_GARDEN_HISTORY",
            ):
                assert hidden not in text
        assert not errors
