from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from kernel.api.app import create_app
from tests.e2e.test_character_binding_isolated import _QuietRequests
from tests.unit.kernel.test_character_binding_api import setup_bound_character

pytestmark = pytest.mark.e2e


def test_player_leaves_autonomy_acts_and_player_returns(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path / "app")
    _, player, _, _, _, _, _ = setup_bound_character(app, token)
    server = make_server("127.0.0.1", 0, app, request_handler=_QuietRequests)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    stop = threading.Event()

    def run():
        while not stop.is_set():
            app.extensions["character_runner"].run_once()
            stop.wait(0.05)

    runner_thread = threading.Thread(target=run, daemon=True)
    server_thread.start()
    runner_thread.start()
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
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{server.server_port}/v2/game", wait_until="networkidle")
        expect(page).to_have_title("TableTop Simulation Kernel")
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        page.get_by_label("Autonomous action limit", exact=True).fill("2")
        page.get_by_role("button", name="Let character act", exact=True).click()
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        expect(page.get_by_text("2 / 2 autonomous actions", exact=False)).to_be_visible()
        expect(page.locator(".event-row")).to_have_count(2)
        assert "handoff" not in page.locator(".event-feed").inner_text().lower()
        page.screenshot(path=str(tmp_path / "controller-desktop.png"), full_page=True)
        page.get_by_role("button", name="Take control", exact=True).click()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        page.get_by_label("Command or dialogue", exact=True).fill("/move east")
        page.get_by_role("button", name="Send proposal", exact=True).click()
        expect(page.locator(".event-row")).to_have_count(3)
        page.set_viewport_size({"width": 390, "height": 844})
        close_navigation = page.get_by_role("button", name="Close navigation", exact=True)
        if close_navigation.first.is_visible():
            close_navigation.first.click()
        page.evaluate("window.scrollTo(0,0)")
        expect(page.get_by_role("button", name="Let character act", exact=True)).to_be_visible()
        page.get_by_label("Autonomous action limit", exact=True).fill("1")
        page.get_by_role("button", name="Let character act", exact=True).click()
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        page.get_by_role("button", name="Take control", exact=True).click()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        page.evaluate("window.scrollTo(0,0)")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "controller-mobile.png"), full_page=True)
        page.screenshot(path=str(tmp_path / "controller-mobile-viewport.png"), full_page=False)
        assert not errors
    finally:
        context.close()
        stop.set()
        runner_thread.join(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
