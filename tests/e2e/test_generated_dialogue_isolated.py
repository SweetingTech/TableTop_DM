from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.cognition.test_dialogue_generation import dialogue_server
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import prompt, setup_scene

pytestmark = pytest.mark.e2e


def test_generated_reply_is_visible_and_control_metadata_stays_out_of_fiction(
    browser, monkeypatch, tmp_path
):
    with dialogue_server(monkeypatch) as requests:
        app = _app(monkeypatch, tmp_path)
        admin, player, card, path, run, target, base = setup_scene(app)
        prompt(admin, base, target, "question")
        with serve_game(app, player, browser) as page:
            page.get_by_label("Autonomous action limit", exact=True).fill("1")
            page.get_by_role("button", name="Let character act", exact=True).click()
            expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
            expect(page.locator(".event-row")).to_have_count(2)
            expect(
                page.get_by_text(
                    "I grew up on the docks; tell me which crossing worries you.", exact=True
                )
            ).to_be_visible()
            assert len(requests) == 1
            assert "handoff" not in page.locator(".event-feed").inner_text().lower()
            assert "profile" not in page.locator(".event-feed").inner_text().lower()
            knowledge = page.evaluate(
                """async url => {
                  const response = await fetch(url);
                  return {status: response.status, cache: response.headers.get('Cache-Control'),
                          payload: await response.json()};
                }""",
                path + "/knowledge?run_id=" + run + "&query=ferry",
            )
            assert knowledge["status"] == 200 and knowledge["cache"] == "no-store"
            assert knowledge["payload"]["items"] == [
                {"text": "The ferry sails at dawn.", "basis": "recollection", "confidence": 1.0}
            ]
            assert knowledge["payload"]["canonical_truth"] is False
            for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
                page.set_viewport_size(viewport)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.get_by_role("button", name="Take control", exact=True).click()
            expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / "generated-dialogue.png"), full_page=True)
