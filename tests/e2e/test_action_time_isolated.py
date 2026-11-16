from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import WSGIRequestHandler, make_server

from kernel.api.app import create_app
from tests.unit.kernel.test_action_time_api import advance_clock, clock_path
from tests.unit.kernel.test_world_time import clock_game

pytestmark = pytest.mark.e2e


class _QuietRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def test_console_waits_for_clock_while_offscreen_work_continues(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    admin, player, card, path, run, target, scope = clock_game(app)
    server = make_server("127.0.0.1", 0, app, request_handler=_QuietRequests)
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
    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/v2/game", wait_until="networkidle")
        composer = page.get_by_label("Command or dialogue", exact=True)
        send = page.get_by_role("button", name="Send proposal", exact=True)
        composer.fill("/guard")
        send.click()
        expect(page.locator(".event-row").filter(has_text="tabletop.combat.guard")).to_have_count(1)
        composer.fill("/move east")
        with page.expect_response(
            lambda response: response.url.endswith("/api/v2/commands")
        ) as early:
            send.click()
        assert early.value.status == 400
        assert early.value.json()["details"] == "body is still completing its previous action"
        expect(page.get_by_role("alert")).to_contain_text("The action was rejected. Refresh")
        expect(page.locator(".entity-detail")).to_contain_text("(0, 0)")
        expect(page.locator(".event-row").filter(has_text="tabletop.spatial.move")).to_have_count(0)
        advance_clock(admin, scope, 6)
        assert (
            admin.get(clock_path(scope)).get_json()["activities"][target]["progress_seconds"] == 6
        )
        composer.fill("/move east")
        send.click()
        expect(page.locator(".entity-detail")).to_contain_text("(1, 0)")
        expect(page.locator(".event-row").filter(has_text="tabletop.spatial.move")).to_have_count(1)
        scene = context.request.get(base + path + "/scene").json()
        own = next(
            row for row in scene["perceived_entities"] if row["entity_id"] == card["entity_id"]
        )
        assert own["action_wait_seconds"] == 1 and not own["guarded"]
        page.screenshot(path=str(tmp_path / "clock-actions-desktop.png"), full_page=True)
        assert not errors
    finally:
        context.close()
        server.shutdown()
        thread.join(timeout=5)
