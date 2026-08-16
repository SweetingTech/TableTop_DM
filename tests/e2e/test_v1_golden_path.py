"""V1 release-candidate browser/API golden-path smoke."""

from __future__ import annotations

import os
import uuid

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("TTDM_BASE_URL", "http://localhost:8000")

pytestmark = pytest.mark.e2e


def _json(response):
    assert response.ok, f"{response.status}: {response.text()}"
    return response.json()


def test_v1_golden_path_dm_setup_player_play_save_import_reload(page: Page):
    suffix = uuid.uuid4().hex[:8]
    passphrase = f"v1-golden-{suffix}"
    campaign_id = None
    gm_query = None

    try:
        page.goto(f"{BASE_URL}/")
        expect(page.get_by_role("link", name="Game Console")).to_be_visible()
        expect(
            page.get_by_role("link", name="Control Plane", exact=True)
        ).to_be_visible()

        campaign = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns",
                data={
                    "slug": f"v1-golden-{suffix}",
                    "name": f"V1 Golden Path {suffix}",
                    "status": "ACTIVE",
                    "mode": "EXPLORATION",
                },
            )
        )
        campaign_id = campaign["id"]

        members = _json(
            page.request.get(f"{BASE_URL}/api/campaigns/{campaign_id}/members")
        )
        gm = next(member for member in members if member["role"] == "GM")
        gm_query = f"principal_id={gm['principal_id']}&join_token=dm-smoke-join-{gm['principal_id']}"

        session = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/sessions?{gm_query}"
            )
        )
        session_id = session["id"]

        player_member = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/members",
                data={"display_name": f"QA Player {suffix}", "role": "PLAYER"},
            )
        )
        player_id = player_member["membership"]["principal_id"]

        join_code = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/join_codes?{gm_query}",
                data={
                    "principal_id": player_id,
                    "session_id": session_id,
                    "label": "V1 golden-path player link",
                },
            )
        )["join_code"]

        maps = _json(page.request.get(f"{BASE_URL}/api/campaigns/{campaign_id}/maps"))
        room = next((row for row in maps if row.get("kind") == "ROOM"), maps[-1])

        pc = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/entities?{gm_query}",
                data={
                    "name": f"Rook {suffix}",
                    "entity_type": "PC",
                    "controlled_by": "HUMAN",
                    "controller_principal_id": player_id,
                    "public_sheet": {"class": "fighter", "x": 5, "y": 5},
                    "hp_current": 12,
                    "hp_max": 12,
                    "ac": 14,
                    "speed": 6,
                },
            )
        )
        npc = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/entities?{gm_query}",
                data={
                    "name": f"Training Dummy {suffix}",
                    "entity_type": "NPC",
                    "controlled_by": "AI_NPC",
                    "public_sheet": {"x": 6, "y": 5},
                    "hp_current": 8,
                    "hp_max": 8,
                    "ac": 10,
                    "speed": 4,
                },
            )
        )
        for entity, x in ((pc, 5), (npc, 6)):
            _json(
                page.request.post(
                    f"{BASE_URL}/api/entities/{entity['id']}/transition_map",
                    data={"map_id": room["id"], "x": x, "y": 5},
                )
            )
            _json(
                page.request.post(
                    f"{BASE_URL}/api/sessions/{session_id}/characters",
                    data={"entity_id": entity["id"]},
                )
            )

        _json(
            page.request.post(
                f"{BASE_URL}/api/maps/{room['id']}/pois?{gm_query}",
                data={
                    "x": 5,
                    "y": 6,
                    "kind": "SIGN",
                    "name": f"Golden Rune {suffix}",
                    "description": "A visible QA marker.",
                    "is_hidden": False,
                },
            )
        )

        page.goto(
            f"{BASE_URL}/game?principal_id={player_id}&join_token={join_code['join_token']}"
        )
        page.wait_for_function(
            "App?.playerState?.principal?.role === 'PLAYER'", timeout=10000
        )
        expect(page.locator("#principalSelect")).to_be_hidden()
        expect(page.locator("#principalName")).to_contain_text(f"QA Player {suffix}")

        state = page.evaluate(
            """async ({pcId}) => {
                const chat = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        campaign_id: App.campaign.id,
                        session_id: App.sessionId,
                        speaker_entity_id: pcId,
                        speaker_principal_id: App.principalId,
                        message: 'V1 golden path player chat',
                    }),
                }).then(async r => ({status: r.status, body: await r.json()}));
                App.selectedEntity = App.entities.find(e => e.id === pcId);
                const move = await App.proposeAction('MOVE', {
                    entity_id: pcId,
                    destination_x: 6,
                    destination_y: 6,
                });
                return {
                    principalId: App.principalId,
                    controlled: App.controlledEntities,
                    chat,
                    moveOk: !!move && !move.error,
                    dmLeakText: document.body.innerText.includes('dm_only')
                        || document.body.innerText.includes('dm_private_notes')
                        || document.body.innerText.includes('The bell is cursed'),
                };
            }""",
            {"pcId": pc["id"]},
        )

        assert state["principalId"] == player_id
        assert pc["id"] in state["controlled"]
        assert state["chat"]["status"] == 200
        assert state["moveOk"] is True
        assert state["dmLeakText"] is False

        _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/mode?{gm_query}",
                data={"mode": "COMBAT"},
            )
        )
        encounter = _json(
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/encounters?{gm_query}",
                data={"session_id": session_id},
            )
        )["encounter"]
        page.reload()
        page.wait_for_function("App?.campaign?.mode === 'COMBAT'", timeout=10000)
        page.wait_for_function(
            "encounterId => (App?.encounters || []).some(e => e.id === encounterId)",
            arg=encounter["id"],
            timeout=10000,
        )
        page.wait_for_function(
            "App?.playerState?.principal?.role === 'PLAYER'", timeout=10000
        )

        save_response = page.request.post(
            f"{BASE_URL}/api/saves/game/export",
            data={"campaign_id": campaign_id, "passphrase": passphrase},
        )
        assert save_response.ok
        save_text = save_response.text()
        assert save_text.startswith("ttdm-save:v1")

        import_conflict = page.evaluate(
            """async ({saveText, passphrase}) => {
                const fd = new FormData();
                fd.append('file', new File([saveText], 'golden.ttdm', {type: 'text/plain'}));
                fd.append('passphrase', passphrase);
                fd.append('replace', 'false');
                const response = await fetch('/api/saves/game/import', {method: 'POST', body: fd});
                return {status: response.status, body: await response.json()};
            }""",
            {"saveText": save_text, "passphrase": passphrase},
        )
        assert import_conflict["status"] == 409

        page.reload()
        page.wait_for_function(
            "App?.playerState?.principal?.role === 'PLAYER'", timeout=10000
        )
        resumed = page.evaluate(
            """() => ({
                principalId: App.principalId,
                sessionId: App.sessionId,
                controlled: App.controlledEntities,
                leak: document.body.innerText.includes('dm_only')
                    || document.body.innerText.includes('dm_private_notes'),
            })"""
        )
        assert resumed["principalId"] == player_id
        assert resumed["sessionId"] == session_id
        assert pc["id"] in resumed["controlled"]
        assert resumed["leak"] is False
    finally:
        if campaign_id and gm_query:
            page.request.post(
                f"{BASE_URL}/api/campaigns/{campaign_id}/purge?{gm_query}"
            )
