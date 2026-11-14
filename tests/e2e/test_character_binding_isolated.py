from __future__ import annotations

import json
import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import WSGIRequestHandler, make_server

from kernel.api.app import create_app
from tests.unit.kernel.test_character_binding_api import setup_bound_character

pytestmark = pytest.mark.e2e


class _QuietRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def test_card_edit_is_pinned_until_explicit_rebind_in_real_spa(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path / "app")
    _, player, card, _, path, run, _ = setup_bound_character(app, token)
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
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "/v2/player", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Player Dashboard", exact=True)).to_be_visible()
        first = context.request.get(base + path + "/context").json()
        page.get_by_role("button", name="Nyra History", exact=False).click()
        page.get_by_label("Backstory", exact=True).fill("Ships and gardens shape my life.")
        with page.expect_response(lambda r: r.request.method == "PATCH") as edited:
            page.get_by_role("button", name="Save character identity", exact=True).click()
        assert edited.value.status == 200
        history = context.request.get(
            base + f"/api/v2/player/characters/{card['character_id']}/history"
        ).json()["items"]
        assert (
            len(history) == 2
            and history[0]["content"]["authored_identity"]["backstory"] == "Raised by sailors."
        )
        assert context.request.get(base + path + "/context").json() == first
        response = context.request.post(
            base + path + "/character-binding",
            data={
                "character_id": card["character_id"],
                "run_id": run,
                "card_revision_id": history[-1]["revision_id"],
                "replaces_binding_id": first["binding"]["binding_id"],
            },
        )
        assert response.status == 200
        assert (
            context.request.get(base + path + "/context").json()["situation"]["identity"][
                "backstory"
            ]
            == "Ships and gardens shape my life."
        )
        page.goto(base + "/v2/game", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        page.get_by_label("Command or dialogue", exact=True).fill("/move east")
        page.get_by_role("button", name="Send proposal", exact=True).click()
        expect(page.locator(".event-row").filter(has_text="tabletop.spatial.move")).to_have_count(1)
        expect(page.locator(".entity-detail")).to_contain_text("(1, 0)")
        assert "SELF_PRIVATE_MAP" not in page.locator(".event-feed").inner_text()
        page.reload(wait_until="networkidle")
        expect(page.locator(".event-row").filter(has_text="tabletop.spatial.move")).to_have_count(1)
        page.screenshot(path=str(tmp_path / "binding-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        toggle = page.get_by_role("button", name="Close navigation", exact=True).first
        if toggle.count():
            toggle.click()
        page.wait_for_function(
            "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "binding-mobile.png"), full_page=True)
        assert not errors
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "checks": [
                        "cookie-authenticated card edit",
                        "immutable history",
                        "pinned context",
                        "explicit successor binding",
                        "movement after binding",
                        "no private fiction in feed",
                        "reload dedup",
                        "mobile overflow",
                        "no page errors",
                    ],
                    "screenshots": str(tmp_path),
                }
            )
        )
    finally:
        context.close()
        server.shutdown()
        thread.join(timeout=5)
