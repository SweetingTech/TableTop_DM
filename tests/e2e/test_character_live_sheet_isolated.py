from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import WSGIRequestHandler, make_server

from kernel.api.app import create_app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene
from tests.unit.kernel.test_tactical_choices import resources

pytestmark = pytest.mark.e2e


class _QuietRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def test_live_sheet_tracks_actions_without_overwriting_card(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    admin, player, card, _, _, _, scope = setup_scene(app)
    resources(app, admin, scope, card["entity_id"], hp=5, mana=8)
    card_path = f"/api/v2/player/characters/{card['character_id']}"
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
        expect(page.get_by_label("Character hit points", exact=True)).to_have_text("5/12")
        expect(page.get_by_text("Mana: 8", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Save status", exact=True)).to_have_count(0)
        expect(page.get_by_label("Current hit points", exact=True)).not_to_be_visible()
        page.get_by_label("Backstory", exact=True).fill(
            "Unsubmitted identity draft survives polling."
        )
        assert (
            context.request.patch(base + card_path, data={"current_hit_points": 999}).status == 400
        )
        healed = context.request.post(
            base + "/api/v2/commands",
            data={
                **scope,
                "embodied_entity_id": card["entity_id"],
                "command_type": "tabletop.magic.invoke",
                "parameters": {"spell_id": "MEND", "target_id": card["entity_id"]},
                "idempotency_key": "live-sheet-heal",
            },
        )
        assert healed.status == 200
        # The visible sheet follows a real canonical action without a reload or card update.
        expect(page.get_by_label("Character hit points", exact=True)).to_have_text(
            "9/12", timeout=9000
        )
        expect(page.get_by_text("Mana: 6", exact=True)).to_be_visible()
        expect(page.get_by_label("Backstory", exact=True)).to_have_value(
            "Unsubmitted identity draft survives polling."
        )
        unchanged = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert unchanged == card
        page.screenshot(path=str(tmp_path / "live-sheet-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        toggle = page.get_by_role("button", name="Close navigation", exact=True).first
        if toggle.count():
            toggle.click()
        page.wait_for_function(
            "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_label("Character resources", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "live-sheet-mobile.png"), full_page=True)

        created = context.request.post(
            base + "/api/v2/player/characters", data={"name": "Unbound setup"}
        )
        assert created.status == 201
        page.get_by_role("button", name="Refresh characters", exact=True).click()
        page.get_by_role("button", name="Unbound setup", exact=False).click()
        expect(page.get_by_role("button", name="Save status", exact=True)).to_be_visible()
        page.get_by_label("Current hit points", exact=True).fill("4")
        with page.expect_response(lambda response: response.request.method == "PATCH") as saved:
            page.get_by_role("button", name="Save status", exact=True).click()
        assert saved.value.status == 200
        assert saved.value.json()["current_hit_points"] == 4
        page.get_by_role("button", name="Nyra History", exact=False).click()
        expect(page.get_by_label("Character hit points", exact=True)).to_have_text("9/12")
        assert (
            admin.put(
                f"/api/v2/admin/users/{card['owner_user_id']}/worlds/{card['world_id']}/roles",
                json={"roles": []},
            ).status_code
            == 200
        )
        refresh = page.get_by_role("button", name="Refresh character state", exact=True)
        refresh.click()
        expect(page.get_by_role("alert")).to_contain_text("no longer have access")
        expect(page.get_by_label("Character hit points", exact=True)).to_have_count(0)
        expect(refresh).to_be_focused()
        expect(page.get_by_role("button", name="Save status", exact=True)).to_have_count(0)
        assert not errors
    finally:
        context.close()
        server.shutdown()
        thread.join(timeout=5)
