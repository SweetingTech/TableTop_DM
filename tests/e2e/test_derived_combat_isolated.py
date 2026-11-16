from __future__ import annotations

import secrets
import threading
import uuid

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from kernel.api.app import create_app
from tests.e2e.test_scene_refresh_isolated import _QuietRequests
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_derived_combat_api import configure_body, prepare_combat

pytestmark = pytest.mark.e2e


def test_console_owned_equipment_live_ability_changes_and_mobile_costs(
    browser, monkeypatch, tmp_path
):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    game = prepare_combat(app)
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
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        draft = page.get_by_label("Command or dialogue", exact=True)
        draft.fill("/equip SHORTSWORD")
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        assert response.value.json()["result"]["result"]["weapon_id"] == "SHORTSWORD"
        expect(draft).to_have_value("")
        page.goto(base + "/v2/player", wait_until="networkidle")
        resources = page.get_by_label("Character resources", exact=True)
        abilities = page.get_by_role("group", name="Campaign abilities", exact=True)
        expect(abilities).to_contain_text("DEX20+5")
        expect(resources.get_by_text("Attack bonus:", exact=False)).to_contain_text("+7")
        configure_body(
            admin,
            base_scope,
            card["entity_id"],
            "stronger",
            ability_scores={"strength": 22, "dexterity": 12},
            equipped_weapon="SHORTSWORD",
        )
        page.get_by_role("button", name="Refresh character state", exact=True).click()
        expect(abilities).to_contain_text("STR22+6")
        expect(resources.get_by_text("Attack bonus:", exact=False)).to_contain_text("+8")
        image = tmp_path / "derived-combat-desktop.png"
        abilities.scroll_into_view_if_needed()
        page.screenshot(path=str(image), full_page=False)
        print(f"DERIVED_COMBAT_DESKTOP_SCREENSHOT={image}")
        advance_clock(admin, base_scope, 6)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/v2/game", wait_until="networkidle")
        draft = page.get_by_label("Command or dialogue", exact=True)
        draft.fill("/equip SPEAR")
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        expect(draft).to_have_value("")
        state = (
            app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base_scope["branch_id"]))
        )
        assert (
            state.projections["tabletop.entities"][card["entity_id"]]["equipped_weapon"] == "SPEAR"
        )
        assert state.projections["tabletop.action_time"][card["entity_id"]]["ready_seconds"] == 12
        assert state.projections["tabletop.entities"][target]["weeded_units"] == 6
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        image = tmp_path / "derived-combat-mobile.png"
        page.screenshot(path=str(image), full_page=False)
        print(f"DERIVED_COMBAT_MOBILE_SCREENSHOT={image}")
        saved = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert saved == card
        assert not errors, errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
