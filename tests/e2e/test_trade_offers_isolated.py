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
from tests.unit.kernel.test_trade_offers_api import identity, prepare_trade
from tests.unit.kernel.test_world_time import api_command

pytestmark = pytest.mark.e2e


def test_visible_quotes_prepare_intents_refresh_and_reject_stale_offer_on_mobile(
    browser, monkeypatch, tmp_path
):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    game, maker, buy, sell = prepare_trade(app)
    admin, player, card, path, run, target, scope = game
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
        page.get_by_role("option").filter(has_text="Marketkeeper").click()
        offers = page.get_by_role("region", name="Trade offers", exact=True)
        expect(offers).to_contain_text("3 food available · 2 gold each")
        draft = page.get_by_label("Command or dialogue", exact=True)
        offers.get_by_role("button", name="Sell SPEAR for 5 gold", exact=True).click()
        expect(draft).to_be_focused()
        expect(draft).to_have_value(f"/trade {identity(buy)} 1")
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        assert response.value.json()["result"]["result"]["price"] == 5
        expect(draft).to_have_value("")
        expect(
            offers.get_by_role("button", name="Sell SPEAR for 5 gold", exact=True)
        ).to_have_count(0)
        offers.scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "trade-desktop.png"), full_page=False)
        advance_clock(admin, scope, 6)
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="networkidle")
        page.get_by_role("option").filter(has_text="Marketkeeper").click()
        offers.get_by_role("button", name="Buy food for 2 gold", exact=True).click()
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        expect(offers).to_contain_text("2 food available")
        advance_clock(admin, scope, 12)
        offers.get_by_role("button", name="Buy food for 2 gold", exact=True).click()
        api_command(
            admin, scope, "tabletop.economy.cancel_offer", {"offer_id": identity(sell)}, "withdraw"
        )
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 400
        expect(draft).to_have_value(f"/trade {identity(sell)} 1")
        expect(page.get_by_role("alert")).to_be_visible()
        state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(scope["branch_id"]))
        body = state.projections["tabletop.entities"][card["entity_id"]]
        assert body["gold"] == 3 and body["inventory"]["food"] == 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "trade-mobile.png"), full_page=False)
        print(f"TRADE_SCREENSHOTS={tmp_path}")
        assert not errors, errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
