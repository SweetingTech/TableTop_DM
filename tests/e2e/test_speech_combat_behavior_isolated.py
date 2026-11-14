from __future__ import annotations

import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from kernel.api.app import create_app
from tests.e2e.test_character_binding_isolated import _QuietRequests
from tests.unit.kernel.test_speech_combat_behavior import prompt, provoke, setup_scene

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("kind", ["speech", "combat"])
def test_player_demonstrations_drive_standin_choices(browser, monkeypatch, tmp_path, kind):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    admin, player, card, path, run, target, base = setup_scene(app)
    if kind == "combat":
        provoke(admin, base, target, card, "browser-provocation")
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
        url = f"http://127.0.0.1:{server.server_port}/v2/game"
        for index in range(4):
            if kind == "speech":
                prompt(admin, base, target, f"browser-prompt-{index}")
            page.goto(url, wait_until="networkidle")
            page.get_by_label("Command or dialogue", exact=True).fill(
                "Hello." if kind == "speech" else "/attack Nearby speaker"
            )
            page.get_by_role("button", name="Send proposal", exact=True).click()
            expect(page.locator(".event-row")).to_have_count(
                (index + 1) * 2 if kind == "speech" else index + 2
            )
        if kind == "speech":
            prompt(admin, base, target, "browser-new-prompt")
            page.reload(wait_until="networkidle")
        profile = page.request.get(
            f"http://127.0.0.1:{server.server_port}{path}/choice-profile?run_id={run}"
        )
        assert profile.ok and profile.json()["comparable_count"] == 4
        page.get_by_label("Autonomous action limit", exact=True).fill("1")
        page.get_by_role("button", name="Let character act", exact=True).click()
        expect(page.get_by_text("Autonomy paused", exact=True)).to_be_visible(timeout=12000)
        expect(page.locator(".event-row")).to_have_count(10 if kind == "speech" else 6)
        simulation = app.extensions["simulation"]
        last = list(simulation.events.values())[-1]
        if kind == "speech":
            assert last.event_type == "tabletop.dialogue.speak"
            assert last.payload["volume"] == "NORMAL" and last.payload["text"].startswith("Hello.")
        else:
            assert last.event_type == "tabletop.combat.attack"
            assert str(last.payload["target_id"]) == target
        assert (
            sum(bool(row.get("choices")) for row in simulation.human_decision_evidence.values())
            == 4
        )
        assert "handoff" not in page.locator(".event-feed").inner_text().lower()
        page.get_by_role("button", name="Take control", exact=True).click()
        expect(page.get_by_text("You are playing", exact=True)).to_be_visible()
        assert not errors
        page.screenshot(path=str(tmp_path / f"history-{kind}-runner.png"), full_page=True)
    finally:
        context.close()
        stop.set()
        worker.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)
