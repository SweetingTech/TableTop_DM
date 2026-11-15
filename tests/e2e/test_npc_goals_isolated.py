from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_npc_goals import advance_game, configure_subjective, say

pytestmark = pytest.mark.e2e


def test_npc_changes_physical_activity_from_belief_without_showing_private_intentions(
    browser, monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    advance_game(admin, base, 20)
    with serve_game(app, player, browser) as page:
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        expect(page.get_by_text("Weeding · 16% · running · work 20", exact=True)).to_be_visible()
        say(
            player,
            base,
            player_card,
            "motive_importance",
            {"motive": "CURIOSITY", "importance": 100},
            subject_id=target,
        )
        advance_game(admin, base, 40)
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Resting · 16% · running · work 20", exact=True)).to_be_visible()
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            text = page.locator("body").inner_text()
            for hidden in (
                "PRIVATE_NPC_VOW",
                "motivation",
                "input_hash",
                "belief_ids",
                "neighbors",
                "persona_version",
            ):
                assert hidden not in text
        assert not errors
