from __future__ import annotations

import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from kernel.api.app import create_app
from tests.e2e.test_character_binding_isolated import _QuietRequests
from tests.unit.kernel.test_character_binding_api import setup_bound_character

pytestmark = pytest.mark.e2e


def test_player_leaves_autonomy_acts_and_player_returns(browser, monkeypatch, tmp_path):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path / "app")
    _, player, card, _, control_path, run_id, _ = setup_bound_character(app, token)
    server = make_server("127.0.0.1", 0, app, request_handler=_QuietRequests)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    stop = threading.Event()

    def run():
        while not stop.is_set():
            app.extensions["character_runner"].run_once()
            stop.wait(0.05)

    runner_thread = threading.Thread(target=run, daemon=True)
    server_thread.start()
    runner_thread.start()
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
    binding_url = f"http://127.0.0.1:{server.server_port}{control_path}/character-binding"

    def read_binding():
        response = context.request.get(binding_url, params={"run_id": run_id})
        assert response.ok
        return response.json()["binding"]

    try:
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"http://127.0.0.1:{server.server_port}/v2/game", wait_until="networkidle")
        expect(page).to_have_title("TableTop Simulation Kernel")
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        binding = read_binding()
        assert (binding["character_id"], binding["entity_id"]) == (
            card["character_id"],
            card["entity_id"],
        )
        pause_policy = page.get_by_text(
            "Your character draws on your play history and its persona. "
            "A paused world stops autonomous actions.",
            exact=True,
        )
        expect(pause_policy).to_be_visible()
        page.get_by_label("Autonomous action limit", exact=True).fill("2")
        with page.expect_response(
            lambda response: (
                urlsplit(response.url).path == control_path + "/control"
                and response.request.method == "POST"
            )
        ) as leaving:
            page.get_by_role("button", name="Let character act", exact=True).click()
        assert leaving.value.ok
        leave_request = leaving.value.request.post_data_json
        assert (
            leave_request["run_id"],
            leave_request["mode"],
            leave_request["expected_epoch"],
        ) == (
            run_id,
            "AUTONOMOUS",
            0,
        )
        assert leave_request["max_steps"] == 2 and leave_request["idempotency_key"]
        assert leaving.value.json()["state"]["epoch"] == 1
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        expect(page.get_by_text("2 / 2 autonomous actions", exact=False)).to_be_visible()
        assert read_binding() == binding
        expect(page.locator(".event-row")).to_have_count(2)
        assert "handoff" not in page.locator(".event-feed").inner_text().lower()
        page.screenshot(path=str(tmp_path / "controller-desktop.png"), full_page=True)
        page.get_by_role("button", name="Take control", exact=True).click()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        page.get_by_label("Command or dialogue", exact=True).fill("/move east")
        page.get_by_role("button", name="Send proposal", exact=True).click()
        expect(page.locator(".event-row")).to_have_count(3)
        page.set_viewport_size({"width": 390, "height": 844})
        close_navigation = page.get_by_role("button", name="Close navigation", exact=True)
        if close_navigation.first.is_visible():
            close_navigation.first.click()
        page.evaluate("window.scrollTo(0,0)")
        expect(page.get_by_role("button", name="Let character act", exact=True)).to_be_visible()
        expect(pause_policy).to_be_visible()
        page.get_by_label("Autonomous action limit", exact=True).fill("1")
        page.get_by_role("button", name="Let character act", exact=True).click()
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        page.get_by_role("button", name="Take control", exact=True).click()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        page.evaluate("window.scrollTo(0,0)")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "controller-mobile.png"), full_page=True)
        page.screenshot(path=str(tmp_path / "controller-mobile-viewport.png"), full_page=False)
        setting = page.get_by_label("On disconnect", exact=True)
        expect(setting).to_have_value("0")
        with page.expect_response(
            lambda response: "/control/presence" in response.url and response.ok
        ):
            setting.select_option("15")
        expect(setting).to_have_value("15")
        page.goto("about:blank")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = player.get(
                control_path + "/control", query_string={"run_id": run_id}
            ).get_json()["control"]
            if state["mode"] == "PAUSED" and state.get("handoff_reason") == "DISCONNECT_TIMEOUT":
                break
            time.sleep(0.15)
        else:
            pytest.fail("the disconnected character did not take its bounded turn")
        page.goto(f"http://127.0.0.1:{server.server_port}/v2/game", wait_until="networkidle")
        expect(page.get_by_text("Connection timed out. Take control when ready.")).to_be_visible()
        assert read_binding() == binding
        expect(pause_policy).to_be_visible()
        expect(page.locator(".event-row")).to_have_count(5)
        assert "timeout" not in page.locator(".event-feed").inner_text().lower()
        with page.expect_response(
            lambda response: (
                urlsplit(response.url).path == control_path + "/control/recap"
                and response.request.method == "GET"
            )
        ) as recap:
            page.get_by_role("button", name="Show character recap", exact=True).click()
        assert recap.value.ok and recap.value.json()["available"]
        assert parse_qs(urlsplit(recap.value.url).query) == {"run_id": [run_id]}
        experience = page.get_by_role("region", name="Character recap", exact=True)
        expect(experience.get_by_role("listitem")).to_have_count(1)
        expect(experience.get_by_role("listitem")).to_contain_text("You see someone move")
        page.screenshot(path=str(tmp_path / "controller-reconnected.png"), full_page=True)
        with page.expect_response(
            lambda response: (
                urlsplit(response.url).path == control_path + "/control"
                and response.request.method == "POST"
            )
        ) as returning:
            page.get_by_role("button", name="Take control", exact=True).click()
        assert returning.value.ok
        return_request = returning.value.request.post_data_json
        assert (
            return_request["run_id"],
            return_request["mode"],
            return_request["expected_epoch"],
        ) == (run_id, "HUMAN", state["epoch"])
        assert return_request["idempotency_key"] != leave_request["idempotency_key"]
        confirmed = returning.value.json()["state"]
        assert (confirmed["mode"], confirmed["epoch"]) == ("HUMAN", state["epoch"] + 1)
        assert read_binding() == binding
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        expect(setting).to_have_value("15")
        assert not errors
    finally:
        context.close()
        stop.set()
        runner_thread.join(timeout=5)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
