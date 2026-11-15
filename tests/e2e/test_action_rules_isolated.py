from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from tests.e2e.test_tactical_choices_isolated import serve_game
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import provoke, setup_scene
from tests.unit.kernel.test_tactical_choices import resources

pytestmark = pytest.mark.e2e


def test_console_casts_registered_intent_and_rejects_rule_override_without_stale_scene(
    browser, monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"], mana=6, known_spells=("MEND",))
    provoke(admin, base, target, card, "threat")
    with serve_game(app, player, browser) as page:
        composer = page.get_by_label("Command or dialogue", exact=True)
        send = page.get_by_role("button", name="Send proposal", exact=True)
        composer.fill("/cast MEND 0 999 heal Nyra History")
        send.click()
        expect(page.get_by_role("alert")).to_contain_text("Unknown target entity")
        expect(page.locator(".event-row")).to_have_count(1)
        composer.fill("/cast MEND Nyra History")
        send.click()
        expect(page.locator(".event-row")).to_have_count(2)
        page.get_by_role("listbox", name="Perceived entities").get_by_role(
            "option", name="Nyra History", exact=False
        ).click()
        expect(page.get_by_text("9 / 12", exact=True)).to_be_visible()
        before = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"])).version
        for parameters in (
            {"spell_id": "MEND", "target_id": card["entity_id"], "power": 999},
            {"spell_id": "ARCANE_BOLT", "target_id": target},
        ):
            outcome = page.evaluate(
                """async body => {
                    const response = await fetch('/api/v2/commands', {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(body)
                    });
                    return response.status;
                }""",
                {
                    **base,
                    "embodied_entity_id": card["entity_id"],
                    "command_type": "tabletop.magic.cast",
                    "parameters": parameters,
                    "idempotency_key": "rejected-browser-intent",
                },
            )
            assert outcome == 400
        assert (
            app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"])).version == before
        )
        composer.fill("/invoke MEND Nyra History")
        send.click()
        expect(page.locator(".event-row")).to_have_count(3)
        expect(page.get_by_text("12 / 12", exact=True)).to_be_visible()
        body = (
            app.extensions["simulation"]
            .states.get(uuid.UUID(base["branch_id"]))
            .projections["tabletop.entities"][card["entity_id"]]
        )
        assert body["hp"] == 12 and body["mana"] == 2
        for viewport in ({"width": 1440, "height": 1100}, {"width": 390, "height": 844}):
            page.set_viewport_size(viewport)
            page.evaluate(
                """() => Promise.all(document.getAnimations()
                    .filter(animation => Number.isFinite(
                        animation.effect?.getComputedTiming().endTime))
                    .map(animation => animation.finished.catch(() => {})))"""
            )
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / "action-rules-console.png"), full_page=True)
