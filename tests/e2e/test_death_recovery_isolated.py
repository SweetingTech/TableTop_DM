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
from tests.unit.kernel.test_death_recovery_api import healer
from tests.unit.kernel.test_tactical_choices import command, resources
from tests.unit.kernel.test_world_time import clock_game

pytestmark = pytest.mark.e2e


def test_console_first_aid_then_clocked_recovery_preserves_authored_card(
    browser, monkeypatch, tmp_path
):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    game = clock_game(app)
    admin, player, card, path, run, target, base_scope = game
    resources(app, admin, base_scope, card["entity_id"], hp=12, mana=8)
    resources(app, admin, base_scope, target, hp=1)
    client, rescuer = healer(app, game)
    resources(app, admin, base_scope, rescuer["entity_id"], known_spells=("ARCANE_BOLT",))
    dropped = command(
        client,
        base_scope,
        rescuer,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": target},
        "drop",
    )
    assert dropped.status_code == 200, dropped.get_json()
    simulation = app.extensions["simulation"]
    name = simulation.entities[(uuid.UUID(base_scope["branch_id"]), uuid.UUID(target))].name
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
        draft.fill(f"/stabilize {name}")
        with page.expect_response(
            lambda response: (
                response.url.endswith("/commands") and response.request.method == "POST"
            )
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        assert response.value.json()["result"]["result"]["status"] == "STABLE"
        expect(draft).to_have_value("")
        page.get_by_role("listbox", name="Perceived entities").get_by_role(
            "option", name=name, exact=False
        ).click()
        expect(page.locator(".entity-detail")).to_contain_text("0 / 12")
        advance_clock(admin, base_scope, 3600)
        expect(page.locator(".entity-detail")).to_contain_text("1 / 12", timeout=10000)
        unchanged = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert unchanged == card
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
