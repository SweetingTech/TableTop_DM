from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from kernel.api.app import create_app
from tests.e2e.test_scene_refresh_isolated import _QuietRequests
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_initiative_api import ordered, start_encounter

pytestmark = pytest.mark.e2e


def test_live_console_waits_for_turn_retains_draft_then_acts(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base_scope = game
    blocked_at = 6 if ordered(receipt)[0] == card["entity_id"] else 0
    if blocked_at:
        advance_clock(admin, base_scope, blocked_at)
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=_QuietRequests)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
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
    errors = []
    try:
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/v2/game", wait_until="networkidle")
        expect(page).to_have_url(base + "/v2/game")
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        draft = page.get_by_label("Command or dialogue", exact=True)
        draft.fill("/guard")
        mark = state.state_hash, state.version
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 400, response.value.json()
        expect(page.get_by_text("The action was rejected.", exact=False)).to_be_visible()
        expect(draft).to_have_value("/guard")
        assert (state.state_hash, state.version) == mark
        advance_clock(admin, base_scope, blocked_at + 6)
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        expect(draft).to_have_value("")
        assert state.projections["tabletop.entities"][card["entity_id"]]["guarded"]
        image = tmp_path / "initiative-desktop.png"
        page.screenshot(path=str(image), full_page=False)
        print(f"INITIATIVE_DESKTOP_SCREENSHOT={image}")
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        image = tmp_path / "initiative-mobile.png"
        page.screenshot(path=str(image), full_page=False)
        print(f"INITIATIVE_MOBILE_SCREENSHOT={image}")
        assert not errors, errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
