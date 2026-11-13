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


def test_authored_identity_build_edit_import_in_isolated_app(browser, monkeypatch, tmp_path):
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
            json={
                "current_password": "admin123",
                "new_password": secrets.token_urlsafe(24),
            },
        ).status_code
        == 200
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
        page.goto(base + "/v2/player", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Player Dashboard", exact=True)).to_be_visible()
        page.get_by_role("button", name="Build character", exact=True).click()
        page.get_by_label("Name", exact=True).fill("Nyra Identity")
        page.get_by_label("Backstory", exact=True).fill("Raised by sailors.")
        page.get_by_label("Motives", exact=True).fill("Find my sister.\nProtect the crew.")
        page.get_by_label("Values", exact=True).fill("Mercy")
        page.get_by_label("Bonds", exact=True).fill("The harbor crew")
        page.get_by_label("Character secrets", exact=True).fill("I hid the map.")
        page.get_by_label("Starting knowledge claims", exact=True).fill("The ferry sails at dawn.")
        with page.expect_response(
            lambda r: r.url.endswith("/player/characters") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Save character", exact=True).click()
        created = response.value.json()
        assert response.value.status == 201
        assert created["authored_identity"]["motives"] == ["Find my sister.", "Protect the crew."]
        expect(page.get_by_role("textbox", name="Backstory", exact=True)).to_have_value(
            "Raised by sailors."
        )
        version = created["card_version"]
        page.get_by_label("Backstory", exact=True).fill("Raised by sailors on the south coast.")
        with page.expect_response(lambda r: r.request.method == "PATCH") as response:
            page.get_by_role("button", name="Save character identity", exact=True).click()
        assert response.value.status == 200
        edited = response.value.json()
        assert edited["card_version"] != version
        page.reload(wait_until="networkidle")
        expect(page.get_by_label("Backstory", exact=True)).to_have_value(
            "Raised by sailors on the south coast."
        )
        page.screenshot(path=str(tmp_path / "identity-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        navigation_toggle = page.get_by_role("button", name="Close navigation", exact=True).first
        if navigation_toggle.count():
            navigation_toggle.click()
        page.wait_for_function(
            "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_label("Character secrets", exact=True).scroll_into_view_if_needed()
        expect(page.get_by_label("Character secrets", exact=True)).to_be_visible()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(tmp_path / "identity-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Import", exact=True).click()
        page.locator('input[type="file"]').set_input_files(
            {
                "name": "hero.json",
                "mimeType": "application/json",
                "buffer": json.dumps(
                    {
                        "name": "Imported Identity",
                        "authored_identity": edited["authored_identity"],
                    }
                ).encode(),
            }
        )
        with page.expect_response(
            lambda r: r.url.endswith("/player/characters") and r.request.method == "POST"
        ) as response:
            page.get_by_role("button", name="Import and save", exact=True).click()
        assert response.value.status == 201
        assert response.value.json()["authored_identity"] == edited["authored_identity"]
        assert not errors
        print(
            json.dumps(
                {
                    "result": "PASS",
                    "checks": [
                        "real build",
                        "private identity edit",
                        "content version",
                        "reload",
                        "JSON import",
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
