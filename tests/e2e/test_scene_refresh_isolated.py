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


def test_scene_refresh_waits_and_never_duplicates_receipts(browser, monkeypatch, tmp_path):
    """Real cookie session, API, kernel and built SPA; delay only subjective projection."""
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
    world = str(app.extensions["demo_ids"]["world_id"])
    password = secrets.token_urlsafe(24)
    created = admin.post(
        "/api/v2/admin/users",
        json={
            "username": "scenereader",
            "temporary_password": password,
            "profile": {"display_name": "Scene Reader"},
        },
    )
    assert created.status_code == 201
    user = created.get_json()["user"]["user_id"]
    assert (
        admin.put(
            f"/api/v2/admin/users/{user}/worlds/{world}/roles", json={"roles": ["PLAYER"]}
        ).status_code
        == 200
    )
    player = app.test_client()
    assert (
        player.post(
            "/api/v2/auth/login", json={"username": "scenereader", "password": password}
        ).status_code
        == 200
    )
    assert (
        player.post(
            "/api/v2/auth/change-password",
            json={"current_password": password, "new_password": secrets.token_urlsafe(24)},
        ).status_code
        == 200
    )
    card = player.post(
        "/api/v2/player/characters",
        json={"world_id": world, "name": "Scene Runner", "creation_method": "GENERATED", "seed": 7},
    )
    assert card.status_code == 201
    game = admin.post("/api/v2/dm/games", json={"world_id": world, "name": "Scene review"})
    assert game.status_code == 201
    game_id = game.get_json()["game_id"]
    assert (
        admin.put(
            f"/api/v2/dm/games/{game_id}/members",
            json={
                "user_id": user,
                "membership_role": "PLAYER",
                "character_id": card.get_json()["character_id"],
            },
        ).status_code
        == 200
    )
    simulation = app.extensions["simulation"]
    projector = simulation.subjective_projector
    assert projector is not None
    pending = []
    simulation.configure_subjective_projector(pending.append)
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
        assert context.request.get(base + "/readyz").json()["ready"] is True
        page = context.new_page()
        errors = []
        posts = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda r: (
                posts.append(r) if r.method == "POST" and r.url.endswith("/commands") else None
            ),
        )
        page.goto(base + "/v2/game", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        version = simulation.states.get(app.extensions["demo_ids"]["branch_id"]).version
        expect(page.get_by_text(f"Projection {version}", exact=True)).to_be_visible()
        composer = page.get_by_label("Command or dialogue", exact=True)
        composer.fill("/move east")
        with page.expect_response(
            lambda r: r.url.endswith("/commands") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200
        cursor = response.value.json()["scene_refresh"]
        with page.expect_response(lambda r: "after_event_id=" in r.url) as waiting:
            expect(
                page.get_by_text("Action accepted. Updating your scene…", exact=True)
            ).to_be_visible()
        assert waiting.value.json()["refresh"]["ready"] is False
        assert len(pending) == 1
        projector(pending.pop())
        expect(
            page.get_by_text(f"Projection {cursor['projection_version']}", exact=True)
        ).to_be_visible()
        expect(page.locator(".event-row").filter(has_text="tabletop.spatial.move")).to_have_count(1)
        expect(page.locator(".entity-detail")).to_contain_text("(1, 0)")
        expect(composer).to_be_focused()
        refresh = page.get_by_role("button", name="Refresh", exact=True)
        refresh.click()
        expect(refresh).to_be_focused()
        expect(page.locator(".event-row").filter(has_text="tabletop.spatial.move")).to_have_count(1)
        assert len(posts) == 1
        simulation.configure_subjective_projector(projector)
        composer.fill("The tide waits for no one.")
        page.get_by_role("button", name="Send proposal", exact=True).click()
        expect(
            page.locator(".event-row").filter(has_text="The tide waits for no one.")
        ).to_have_count(1)
        page.reload(wait_until="networkidle")
        expect(
            page.locator(".event-row").filter(has_text="The tide waits for no one.")
        ).to_have_count(1)
        assert len(posts) == 2
        page.screenshot(path=str(tmp_path / "scene-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        toggle = page.get_by_role("button", name="Close navigation", exact=True).first
        if toggle.count():
            toggle.click()
        page.wait_for_function(
            "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "scene-mobile.png"), full_page=True)
        assert not errors
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "checks": [
                        "cookie-authorized move",
                        "delayed projection barrier",
                        "automatic position/version refresh",
                        "manual refresh dedup",
                        "GET-only refresh",
                        "dialogue/reload",
                        "keyboard focus",
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
