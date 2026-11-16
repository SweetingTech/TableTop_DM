from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import WSGIRequestHandler, make_server

from kernel.api.app import create_app
from tests.unit.kernel.test_action_time_api import advance_clock, clock_path
from tests.unit.kernel.test_timed_effects_api import condition
from tests.unit.kernel.test_world_time import clock_game

pytestmark = pytest.mark.e2e


class _QuietRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def test_live_sheet_recovers_from_timed_condition_without_rewriting_card(
    browser, monkeypatch, tmp_path
):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    admin, player, card, path, run, target, base_scope = clock_game(app)
    condition(admin, base_scope, card["entity_id"])
    condition(admin, base_scope, target, key="stunned-worker")
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
        page.goto(base + "/v2/player", wait_until="networkidle")
        resources = page.get_by_label("Character resources", exact=True)
        expect(resources.locator(".status")).to_have_text("INCAPACITATED")
        expect(page.get_by_text("Conditions: stunned", exact=True)).to_be_visible()
        move = {
            **base_scope,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.spatial.move",
            "parameters": {"dx": 1, "dy": 0},
            "idempotency_key": "recover-move",
        }
        assert context.request.post(base + "/api/v2/commands", data=move).status == 400
        advance_clock(admin, base_scope, 5)
        assert (
            admin.get(clock_path(base_scope)).get_json()["activities"][target]["progress_seconds"]
            == 0
        )
        page.get_by_role("button", name="Refresh character state", exact=True).click()
        expect(resources.locator(".status")).to_have_text("ALIVE")
        expect(page.get_by_text("Conditions: None", exact=True)).to_be_visible()
        assert context.request.post(base + "/api/v2/commands", data=move).status == 200
        advance_clock(admin, base_scope, 10)
        assert (
            admin.get(clock_path(base_scope)).get_json()["activities"][target]["progress_seconds"]
            == 5
        )
        unchanged = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert unchanged == card
        page.screenshot(path=str(tmp_path / "timed-effects-desktop.png"), full_page=True)
        assert not errors
    finally:
        context.close()
        server.shutdown()
        thread.join(timeout=5)
