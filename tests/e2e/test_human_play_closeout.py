from __future__ import annotations

import secrets
import threading
import uuid

import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from kernel.database import transaction
from tests.e2e.test_roster_assignment_isolated import _player
from tests.e2e.test_scene_refresh_isolated import _QuietRequests
from tests.integration.conftest import integration_stack  # noqa: F401 -- expose isolated DB fixture

pytestmark = pytest.mark.e2e


def test_two_cookie_clients_invite_act_resynchronize_switch_and_survive_restart(
    browser,
    integration_stack,  # noqa: F811 -- imported pytest fixture
    monkeypatch,
    tmp_path,
):
    """Actual built SPA/API/kernel/PostgreSQL; no fabricated scene/command responses."""
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("REDIS_URL", integration_stack.redis_url)
    monkeypatch.delenv("QDRANT_URL", raising=False)
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
    world = admin.post(
        "/api/v2/worlds", json={"name": "Human closeout " + uuid.uuid4().hex[:8]}
    ).get_json()
    world_id = world["world_id"]
    first, a_card, a_client = _player(admin, app, world_id, uuid.uuid4().hex[:8], "Nyra Acceptance")
    second, b_card, b_client = _player(
        admin, app, world_id, uuid.uuid4().hex[:8], "Tarin Acceptance"
    )
    for user, card, client in ((first, a_card, a_client), (second, b_card, b_client)):
        assert (
            admin.put(
                f"/api/v2/admin/users/{user}/worlds/{world_id}/roles", json={"roles": ["PLAYER"]}
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v2/player/characters/{card['character_id']}",
                json={"maximum_hit_points": 30, "current_hit_points": 30, "armor_class": 1},
            ).status_code
            == 200
        )
    game = admin.post(
        "/api/v2/dm/games", json={"world_id": world_id, "name": "Human acceptance table"}
    ).get_json()
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=_QuietRequests)
    port = server.server_port
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    base = f"http://127.0.0.1:{port}"
    stop = threading.Event()
    projection_errors = []

    def project():
        projector = WorldEventProjector(integration_stack.database_url)
        while not stop.wait(0.05):
            try:
                projector.run_once(limit=1000)
            except Exception as error:
                projection_errors.append(type(error).__name__)
                return

    projecting = threading.Thread(target=project, daemon=True)
    projecting.start()
    contexts = []
    errors = []

    def page_for(client):
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        contexts.append(context)
        context.add_cookies(
            [
                {
                    "name": "ttdm_session",
                    "value": client.get_cookie("ttdm_session").value,
                    "domain": "127.0.0.1",
                    "path": "/",
                }
            ]
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        return context, page

    def command(page, text):
        page.get_by_label("Command or dialogue", exact=True).fill(text)
        with page.expect_response(
            lambda response: (
                response.url.endswith("/commands") and response.request.method == "POST"
            )
        ) as response:
            page.get_by_role("button", name="Send proposal", exact=True).click()
        assert response.value.status == 200, response.value.json()
        receipt = response.value.json()
        expect(
            page.get_by_text(
                f"Projection {receipt['scene_refresh']['projection_version']}", exact=True
            )
        ).to_be_visible()
        return receipt

    def choose_body(page, entity_id):
        page.locator("label").filter(has_text="Embodied viewpoint").locator("select").select_option(
            entity_id
        )

    try:
        _, dm = page_for(admin)
        dm.goto(base + "/v2/dm", wait_until="networkidle")
        dm.locator("label.context-control").filter(has_text="Active world").locator(
            "select"
        ).select_option(world_id)
        expect(dm.get_by_role("heading", name="Dungeon Master", exact=True)).to_be_visible()
        for user, card in ((first, a_card), (second, b_card)):
            dm.locator("label").filter(has_text="Eligible user").locator("select").select_option(
                user
            )
            character = dm.locator("label").filter(has_text="Playable character").locator("select")
            expect(character.get_by_role("option", name=card["name"], exact=False)).to_have_count(1)
            character.select_option(card["character_id"])
            with dm.expect_response(
                lambda response: (
                    response.url.endswith(f"/dm/games/{game['game_id']}/members")
                    and response.request.method == "PUT"
                )
            ) as invitation:
                dm.get_by_role("button", name="Invite", exact=True).click()
            assert invitation.value.status == 200
            expect(dm.locator("article.stack-row").filter(has_text=card["name"])).to_have_count(1)
        cards = a_client.get("/api/v2/player/characters").get_json()["items"]
        a_card = next(row for row in cards if row["character_id"] == a_card["character_id"])
        b_card = next(
            row
            for row in b_client.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == b_card["character_id"]
        )
        scope = {
            "world_id": world_id,
            "branch_id": world["canonical_branch_id"],
            "run_id": world["current_run_id"],
        }
        for index, position in enumerate(((-2, 0), (-2, 1), (0, 2), (1, 2))):
            response = admin.post(
                "/api/v2/commands",
                json={
                    **scope,
                    "command_type": "tabletop.entity.spawn",
                    "parameters": {
                        "entity_id": str(uuid.uuid4()),
                        "name": f"Yard witness {index}",
                        "entity_type": "NPC",
                        "public_state": {
                            "x": position[0],
                            "y": position[1],
                            "zone_id": "world",
                            "hp": 10,
                        },
                        "secret_state": {"note": "PRIVATE_BODY_NOTE"},
                    },
                    "idempotency_key": f"witness-{index}",
                },
            )
            assert response.status_code == 200
        reserve = a_client.post(
            "/api/v2/player/characters", json={"world_id": world_id, "name": "Distant Acceptance"}
        ).get_json()
        backup = admin.post(
            "/api/v2/dm/games", json={"world_id": world_id, "name": "Second seat"}
        ).get_json()
        assert (
            admin.put(
                f"/api/v2/dm/games/{backup['game_id']}/members",
                json={"user_id": first, "character_id": reserve["character_id"]},
            ).status_code
            == 200
        )
        reserve = next(
            row
            for row in a_client.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == reserve["character_id"]
        )
        for step in range(14):
            assert (
                a_client.post(
                    "/api/v2/commands",
                    json={
                        **scope,
                        "command_type": "tabletop.spatial.move",
                        "embodied_entity_id": reserve["entity_id"],
                        "parameters": {"dx": 1, "dy": 0},
                        "idempotency_key": f"distant-{step}",
                    },
                ).status_code
                == 200
            )
        assert (
            admin.post(
                "/api/v2/commands",
                json={
                    **scope,
                    "command_type": "tabletop.map.configure",
                    "parameters": {
                        "zone_id": "world",
                        "name": "Acceptance yard",
                        "min_x": -4,
                        "max_x": 4,
                        "min_y": -4,
                        "max_y": 4,
                    },
                    "idempotency_key": "yard-map",
                },
            ).status_code
            == 200
        )
        a_context, a = page_for(a_client)
        b_context, b = page_for(b_client)
        for page in (a, b):
            page.goto(base + "/v2/game", wait_until="networkidle")
            expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
        choose_body(a, a_card["entity_id"])
        expect(a.locator(".map-token")).to_have_count(6)
        expect(
            a.get_by_role("heading", name="Perceived Acceptance yard", exact=True)
        ).to_be_visible()
        command_requests = []
        a.on(
            "request",
            lambda request: (
                command_requests.append(request.url)
                if request.method == "POST" and request.url.endswith("/commands")
                else None
            ),
        )
        unsupported = "/teleport moon"
        draft = a.get_by_label("Command or dialogue", exact=True)
        draft.fill(unsupported)
        a.get_by_role("button", name="Send proposal", exact=True).click()
        expect(
            a.get_by_text(
                "Unsupported command. Use /move, /attack, /guard, /stabilize, /cast, /invoke, "
                "or type dialogue.",
                exact=True,
            )
        ).to_be_visible()
        expect(draft).to_have_value(unsupported)
        assert command_requests == [], "Unsupported input must not post a canonical command"
        command(a, "/move east")
        assert len(command_requests) == 1
        expect(
            b.get_by_role("listbox", name="Perceived entities").get_by_role(
                "option", name="Nyra Acceptance", exact=False
            )
        ).to_contain_text("(1, 0)", timeout=10000)
        token = a.get_by_role("button", name="Inspect Nyra Acceptance on map", exact=True)
        assert token.evaluate("node => parseFloat(node.style.left)") == pytest.approx(100 * 5.5 / 9)
        command(b, "/move north")
        expect(
            a.get_by_role("listbox", name="Perceived entities").get_by_role(
                "option", name="Tarin Acceptance", exact=False
            )
        ).to_contain_text("(0, -1)", timeout=10000)
        phrase = "The lantern belongs to our crew."
        command(a, phrase)
        expect(b.locator(".event-row").filter(has_text=phrase)).to_have_count(1, timeout=10000)
        for _ in range(20):
            receipt = command(a, "/attack Tarin Acceptance")
            if receipt["result"]["result"]["damage"] > 0:
                break
        hp = receipt["result"]["result"]["hp_after"]
        assert 0 < hp < 30
        for page in (a, b):
            page.get_by_role("listbox", name="Perceived entities").get_by_role(
                "option", name="Tarin Acceptance", exact=False
            ).click()
            expect(page.locator(".entity-detail")).to_contain_text(f"{hp} / 30", timeout=10000)
        a.get_by_label("Command or dialogue", exact=True).fill("UNSENT_PRIVATE_DRAFT")
        choose_body(a, reserve["entity_id"])
        expect(a.get_by_label("Command or dialogue", exact=True)).to_have_value("")
        expect(a.locator(".event-row").filter(has_text=phrase)).to_have_count(0)
        choose_body(a, a_card["entity_id"])
        expect(a.locator(".event-row").filter(has_text=phrase)).to_have_count(1)
        b_context.set_offline(True)
        expect(b.get_by_role("status").filter(has_text="Connection interrupted")).to_be_visible(
            timeout=10000
        )
        command(a, "/move south")
        b_context.set_offline(False)
        expect(
            b.get_by_role("listbox", name="Perceived entities").get_by_role(
                "option", name="Nyra Acceptance", exact=False
            )
        ).to_contain_text("(1, 1)", timeout=10000)
        expect(b.get_by_text("Connection interrupted", exact=False)).to_have_count(0)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)
        app = create_app(artifact_root=tmp_path / "app")
        server = make_server("127.0.0.1", port, app, threaded=True, request_handler=_QuietRequests)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        assert a_context.request.get(base + "/readyz").json()["ready"] is True
        a.reload(wait_until="networkidle")
        choose_body(a, a_card["entity_id"])
        expect(
            a.get_by_role("listbox", name="Perceived entities").get_by_role(
                "option", name="Nyra Acceptance", exact=False
            )
        ).to_contain_text("(1, 1)")
        for page in (a, b):
            page.get_by_role("listbox", name="Perceived entities").get_by_role(
                "option", name="Tarin Acceptance", exact=False
            ).click()
            expect(page.locator(".entity-detail")).to_contain_text(f"{hp} / 30", timeout=10000)
            expect(page.locator(".event-row").filter(has_text=phrase)).to_have_count(1)
            assert "PRIVATE_BODY_NOTE" not in page.locator("body").inner_text()
        a.locator(".entity-detail").scroll_into_view_if_needed()
        a.screenshot(path=str(tmp_path / "human-play-desktop.png"), full_page=True)
        a.set_viewport_size({"width": 390, "height": 844})
        close_navigation = a.get_by_role("button", name="Close navigation", exact=True).first
        if close_navigation.count():
            close_navigation.click()
        a.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        mobile_phrase = "We are still here after the restart."
        command(a, mobile_phrase)
        expect(b.locator(".event-row").filter(has_text=mobile_phrase)).to_have_count(
            1, timeout=10000
        )
        assert a.evaluate("document.documentElement.scrollWidth <= innerWidth")
        a.screenshot(path=str(tmp_path / "human-play-mobile.png"), full_page=True)
        assert not errors, errors
        assert not projection_errors, projection_errors
        print(
            "A8 PASS: two cookie clients, UI invite/bind, unsupported command rejected "
            "without POST or draft loss, movement/health/speech polling, "
            "six map tokens, scoped viewpoint switch, reconnect, "
            "PostgreSQL app restart, desktop/mobile."
        )
    except BaseException:
        with transaction(dsn=integration_stack.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT last_error,attempts,count(*) FROM sim.outbox "
                    "WHERE published_at IS NULL GROUP BY last_error,attempts"
                )
                print("Unpublished projector diagnostics:", cursor.fetchall())
        for index, context in enumerate(contexts):
            for page_index, page in enumerate(context.pages):
                page.screenshot(path=str(tmp_path / f"failure-{index}-{page_index}.png"))
        raise
    finally:
        for context in contexts:
            context.close()
        stop.set()
        projecting.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)
