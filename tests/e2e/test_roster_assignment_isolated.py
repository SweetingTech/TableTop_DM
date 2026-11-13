from __future__ import annotations

import json
import secrets
import threading

import pytest
from playwright.sync_api import expect
from werkzeug.serving import WSGIRequestHandler, make_server

from kernel.api.app import create_app

pytestmark = pytest.mark.e2e


class _QuietRequests(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


def _player(admin, app, world, suffix, character_name):
    temporary = secrets.token_urlsafe(24)
    created = admin.post(
        "/api/v2/admin/users",
        json={
            "username": f"rosterplayer{suffix}",
            "temporary_password": temporary,
            "profile": {"display_name": f"Roster Player {suffix}"},
        },
    )
    assert created.status_code == 201
    user_id = created.get_json()["user"]["user_id"]
    assert (
        admin.put(
            f"/api/v2/admin/users/{user_id}/worlds/{world}/roles",
            json={"roles": ["PLAYER", "DM"]},
        ).status_code
        == 200
    )
    client = app.test_client()
    assert (
        client.post(
            "/api/v2/auth/login", json={"username": f"rosterplayer{suffix}", "password": temporary}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v2/auth/change-password",
            json={"current_password": temporary, "new_password": secrets.token_urlsafe(24)},
        ).status_code
        == 200
    )
    character = client.post(
        "/api/v2/player/characters",
        json={"world_id": world, "name": character_name, "creation_method": "GENERATED", "seed": 7},
    )
    assert character.status_code == 201
    return user_id, character.get_json(), client


def test_roster_pending_lookup_invite_and_update_in_isolated_app(browser, monkeypatch, tmp_path):
    """Use a real API and built SPA; delay only the selected player's HTTP lookup."""
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path / "app")
    admin = app.test_client()
    assert (
        admin.post(
            "/api/v2/auth/login", json={"username": "admin", "password": "admin123"}
        ).status_code
        == 200
    )
    assert (
        admin.post(
            "/api/v2/auth/change-password",
            json={"current_password": "admin123", "new_password": secrets.token_urlsafe(24)},
        ).status_code
        == 200
    )
    world = admin.get("/api/v2/worlds").get_json()[0]["world_id"]
    first_id, _, first_client = _player(admin, app, world, "A", "Nyra Browser")
    second_id, second_character, _ = _player(admin, app, world, "B", "Tarin Browser")
    created = admin.post(
        "/api/v2/dm/games", json={"world_id": world, "name": "Isolated roster review"}
    )
    assert created.status_code == 201
    game_id = created.get_json()["game_id"]
    assert (
        first_client.get(f"/api/v2/dm/games/{game_id}/users/{second_id}/characters").status_code
        == 403
    )

    server = make_server("127.0.0.1", 0, app, request_handler=_QuietRequests)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    context.add_cookies(
        [
            {
                "name": "ttdm_session",
                "value": admin.get_cookie("ttdm_session").value,
                "domain": "127.0.0.1",
                "path": "/",
            }
        ]
    )
    try:
        assert context.request.get(base + "/readyz").json()["ready"] is True
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/v2/dm", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Dungeon Master", exact=True)).to_be_visible()
        user = page.locator("label").filter(has_text="Eligible user").locator("select")
        role = page.locator("label").filter(has_text="Membership role").locator("select")
        character_select = (
            page.locator("label").filter(has_text="Playable character").locator("select")
        )
        user.select_option(first_id)
        expect(page.get_by_role("option", name="Nyra Browser", exact=False)).to_have_count(1)
        delayed = []
        pattern = f"**/api/v2/dm/games/{game_id}/users/{second_id}/characters"
        page.route(pattern, lambda route: delayed.append(route))
        with page.expect_request(pattern):
            user.select_option(second_id)
        expect(character_select).to_be_disabled()
        expect(page.get_by_role("button", name="Invite", exact=True)).to_be_disabled()
        expect(page.get_by_role("option", name="Nyra Browser", exact=False)).to_have_count(0)
        expect(page.get_by_text("Loading characters…", exact=True)).to_be_visible()
        page.screenshot(path=str(tmp_path / "pending-desktop.png"), full_page=True)
        assert len(delayed) == 1
        delayed.pop().continue_()
        page.unroute(pattern)
        expect(page.get_by_role("option", name="Tarin Browser", exact=False)).to_have_count(1)
        character_select.select_option(second_character["character_id"])
        page.get_by_role("button", name="Invite", exact=True).click()
        member_row = page.locator("article.stack-row").filter(has_text="Roster Player B")
        expect(member_row.get_by_text("Tarin Browser", exact=True)).to_be_visible()
        role.select_option("CO_DM")
        expect(character_select).to_have_count(0)
        page.get_by_role("button", name="Update member", exact=True).click()
        expect(member_row.get_by_text("Co-DM", exact=True)).to_be_visible()
        role.select_option("PLAYER")
        expect(page.get_by_role("option", name="Tarin Browser", exact=False)).to_have_count(1)
        character_select.select_option(second_character["character_id"])
        page.get_by_role("button", name="Update member", exact=True).click()
        expect(member_row.get_by_text("Tarin Browser", exact=True)).to_be_visible()
        members = admin.get("/api/v2/games").get_json()["items"][0]["members"]
        member = next(row for row in members if row["user_id"] == second_id)
        assert member["character_id"] == second_character["character_id"]
        assert member["membership_role"] == "PLAYER"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "assigned-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "assigned-mobile.png"), full_page=True)
        assert not errors, errors
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "checks": [
                        "ready",
                        "authorized lookup",
                        "pending lookup clears choices and disables saves",
                        "real invite/update",
                        "player/co-DM switching",
                        "desktop/mobile overflow",
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
