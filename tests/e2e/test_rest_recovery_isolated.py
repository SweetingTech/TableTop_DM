from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from kernel.api.app import create_app
from tests.e2e.test_scene_refresh_isolated import _QuietRequests
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_rest_recovery_api import prepare_rest

pytestmark = pytest.mark.e2e


def test_console_long_rest_live_sheet_and_mobile_interruption(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base_scope = game
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
        draft.fill("/rest long")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/commands") and response.request.method == "POST"
            )
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        assert response.value.json()["result"]["result"]["duration_seconds"] == 28800
        expect(draft).to_have_value("")
        page.goto(base + "/v2/player", wait_until="networkidle")
        resources = page.get_by_label("Character resources", exact=True)
        expect(resources.get_by_text("2/12", exact=True)).to_be_visible()
        advance_clock(admin, base_scope, 3600)
        page.reload(wait_until="networkidle")
        expect(resources.get_by_text("5/12", exact=True)).to_be_visible()
        advance_clock(admin, base_scope, 28800)
        page.reload(wait_until="networkidle")
        expect(resources.get_by_text("12/12", exact=True)).to_be_visible()
        screenshot = tmp_path / "rest-desktop.png"
        page.screenshot(path=str(screenshot), full_page=False)
        print(f"REST_DESKTOP_SCREENSHOT={screenshot}")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/v2/game", wait_until="networkidle")
        draft = page.get_by_label("Command or dialogue", exact=True)
        for text in ("/rest short", "/guard"):
            draft.fill(text)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/commands") and response.request.method == "POST"
                )
            ) as response:
                page.get_by_role("button", name="Send proposal", exact=True).click()
            assert response.value.status == 200, response.value.json()
            expect(draft).to_have_value("")
        assert state.projections["tabletop.activities"][card["entity_id"]]["status"] == "CANCELLED"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        screenshot = tmp_path / "rest-mobile.png"
        page.screenshot(path=str(screenshot), full_page=False)
        print(f"REST_MOBILE_SCREENSHOT={screenshot}")
        unchanged = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert unchanged == card
        assert not errors, errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
