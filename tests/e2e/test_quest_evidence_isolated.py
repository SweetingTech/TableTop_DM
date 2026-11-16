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
from tests.unit.kernel.test_quest_evidence_api import prepare_quest

pytestmark = pytest.mark.e2e


def test_console_quest_accept_outcome_progress_and_once_only_reward_on_mobile(
    browser, monkeypatch, tmp_path
):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    game, maker, buy, sell, quest = prepare_quest(app)
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
    errors, requests = [], []
    try:
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                requests.append(request.url) if request.url.endswith("/commands") else None
            ),
        )
        page.goto(base + "/v2/game", wait_until="networkidle")
        page.get_by_role("option").filter(has_text="Marketkeeper").click()
        offered = page.get_by_role("region", name="Offered quests", exact=True)
        expect(offered).to_contain_text("Reward: 7 gold · 1 food")
        offered.get_by_role("button", name="Accept A market errand", exact=True).click()
        draft = page.get_by_label("Command or dialogue", exact=True)
        expect(draft).to_be_focused()
        expect(draft).to_have_value(f"/quest accept {quest}")

        def send():
            with page.expect_response(
                lambda r: r.url.endswith("/commands") and r.request.method == "POST"
            ) as response:
                page.get_by_role("button", name="Send proposal", exact=True).click()
            assert response.value.status == 200, response.value.json()
            expect(draft).to_have_value("")
            return response.value.json()

        send()
        journal = page.get_by_role("region", name="Personal quest journal", exact=True)
        expect(journal).to_contain_text("In progress")
        expect(offered).to_have_count(0)
        advance_clock(admin, scope, 6)
        draft.fill("/move east")
        send()
        expect(journal).to_contain_text("Reach the road · 1 / 1")
        expect(journal).to_contain_text("Deliver a spear · 0 / 1")
        advance_clock(admin, scope, 7)
        page.get_by_role("region", name="Trade offers", exact=True).get_by_role(
            "button", name="Sell SPEAR for 5 gold", exact=True
        ).click()
        send()
        expect(journal).to_contain_text("Ready for reward")
        journal.scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "quest-desktop.png"), full_page=False)
        advance_clock(admin, scope, 13)
        page.set_viewport_size({"width": 390, "height": 844})
        journal.get_by_role("button", name="Claim reward for A market errand", exact=True).click()
        paid = send()
        assert paid["result"]["result"]["status"] == "CLAIMED"
        expect(journal).to_contain_text("Reward received")
        expect(journal.get_by_role("button", name="Claim reward", exact=False)).to_have_count(0)
        state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(scope["branch_id"]))
        body = state.projections["tabletop.entities"][card["entity_id"]]
        assert body["gold"] == 12 and body["inventory"]["food"] == 1
        before = len(requests)
        draft.fill(f"/quest claim {quest} 1000")
        page.get_by_role("button", name="Send proposal", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Use /quest")
        expect(draft).to_have_value(f"/quest claim {quest} 1000")
        assert len(requests) == before
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        journal.scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "quest-mobile.png"), full_page=False)
        print(f"QUEST_SCREENSHOTS={tmp_path}")
        assert not errors, errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
