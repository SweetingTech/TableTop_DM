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


def test_player_demonstrates_movement_and_standin_reuses_it(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path / "app")
    _, player, _, _, path, run, _ = setup_bound_character(app, token)
    server = make_server("127.0.0.1", 0, app, request_handler=_QuietRequests)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    stop = threading.Event()

    def run_worker():
        while not stop.is_set():
            app.extensions["character_runner"].run_once()
            stop.wait(0.05)

    worker = threading.Thread(target=run_worker, daemon=True)
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
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{server.server_port}/v2/game", wait_until="networkidle")
        for index in range(5):
            page.get_by_label("Command or dialogue", exact=True).fill("/move north")
            page.get_by_role("button", name="Send proposal", exact=True).click()
            expect(page.locator(".event-row")).to_have_count(index + 1)
        profile_response = page.request.get(
            f"http://127.0.0.1:{server.server_port}{path}/behavior-profile?run_id={run}"
        )
        assert profile_response.ok
        assert profile_response.json()["comparable_count"] >= 3
        page.get_by_label("Autonomous action limit", exact=True).fill("1")
        page.get_by_role("button", name="Let character act", exact=True).click()
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        expect(page.locator(".event-row")).to_have_count(6)
        simulation = app.extensions["simulation"]
        assert list(simulation.events.values())[-1].payload["destination"]["y"] == -6
        assert len(simulation.human_decision_evidence) == 5
        assert "handoff" not in page.locator(".event-feed").inner_text().lower()
        assert not errors
        page.screenshot(path=str(tmp_path / "history-driven-runner.png"), full_page=True)
    finally:
        context.close()
        stop.set()
        worker.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)
