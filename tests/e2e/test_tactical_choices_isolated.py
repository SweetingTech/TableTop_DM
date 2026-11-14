from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from tests.e2e.test_character_binding_isolated import _QuietRequests
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import provoke, setup_scene
from tests.unit.kernel.test_tactical_choices import resources

pytestmark = pytest.mark.e2e


@contextmanager
def serve_game(app, player, browser):
    server = make_server("127.0.0.1", 0, app, request_handler=_QuietRequests)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    stop = threading.Event()

    def run():
        while not stop.is_set():
            app.extensions["character_runner"].run_once()
            stop.wait(0.05)

    worker = threading.Thread(target=run, daemon=True)
    serving.start()
    worker.start()
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    context.add_cookies(
        [
            {
                "name": "ttdm_session",
                "value": player.get_cookie("ttdm_session").value,
                "domain": "127.0.0.1",
                "path": "/",
            }
        ]
    )
    try:
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{server.server_port}/v2/game", wait_until="networkidle")
        yield page
    finally:
        context.close()
        stop.set()
        worker.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)


def test_player_guards_casts_and_runner_chooses_resource_aware_healing(
    browser, monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"], hp=5, mana=4)
    provoke(admin, base, target, card, "attacked")
    with serve_game(app, player, browser) as page:
        for index, text in enumerate(("/guard", "/invoke ARCANE_BOLT Nearby speaker")):
            page.get_by_label("Command or dialogue", exact=True).fill(text)
            page.get_by_role("button", name="Send proposal", exact=True).click()
            expect(page.locator(".event-row")).to_have_count(index + 2)
        page.get_by_label("Autonomous action limit", exact=True).fill("1")
        page.get_by_role("button", name="Let character act", exact=True).click()
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        expect(page.locator(".event-row")).to_have_count(4)
        last = list(app.extensions["simulation"].events.values())[-1]
        assert last.event_type == "tabletop.magic.invoke" and last.payload["spell_id"] == "MEND"
        assert last.payload["mana_after"] == 0
        page.get_by_role("button", name="Take control", exact=True).click()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        page.screenshot(path=str(tmp_path / "tactical-choice-runner.png"), full_page=True)
