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


def test_browser_character_advice_requires_separate_kernel_submission(
    browser, monkeypatch, tmp_path
):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path / "app")
    _, player, _, _, path, run, _ = setup_bound_character(app, token)
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
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        before = (
            app.extensions["simulation"].states.get(app.extensions["demo_ids"]["branch_id"]).version
        )
        args = {
            "path": path + "/character-proposals",
            "body": {"run_id": run, "idempotency_key": "browser-advice"},
        }
        script = """async ({path, body}) => {
            const response = await fetch(path, {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            return {status: response.status, receipt: await response.json()};
        }"""
        advice = page.evaluate(script, args)
        assert advice["status"] == 200 and advice["receipt"]["committed"] is False
        assert page.evaluate(script, args) == advice
        assert (
            app.extensions["simulation"].states.get(app.extensions["demo_ids"]["branch_id"]).version
            == before
        )
        expect(page.locator(".entity-detail")).to_contain_text("(0, 0)")
        submitted = page.evaluate(
            script, {"path": "/api/v2/commands", "body": advice["receipt"]["outcome"]["proposal"]}
        )
        assert submitted["status"] == 200
        # Re-entering the console reloads its authorized scene after external submission.
        page.reload(wait_until="networkidle")
        movement = advice["receipt"]["outcome"]["proposal"]["parameters"]
        expect(page.locator(".entity-detail")).to_contain_text(
            f"({movement['dx']}, {movement['dy']})"
        )
        assert not errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
