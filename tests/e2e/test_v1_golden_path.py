"""V1 release-candidate browser/API golden-path smoke."""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("TTDM_BASE_URL", "http://localhost:8000")

pytestmark = pytest.mark.e2e


def test_v1_golden_path_seeded_campaign_player_boot_chat_save_reload(page: Page):
    page.goto(f"{BASE_URL}/")
    expect(page.get_by_role("link", name="Game Console")).to_be_visible()
    expect(page.get_by_role("link", name="Control Plane", exact=True)).to_be_visible()

    page.goto(f"{BASE_URL}/game")
    page.wait_for_function("window.__TTDM_PLAYER_STATE_LOADED === true", timeout=10000)
    expect(page.locator("#principalName")).not_to_have_text("--")

    state = page.evaluate(
        """async () => {
            const principalId = App.principalId;
            const sessionId = App.sessionId;
            const campaignId = App.campaign.id;
            const controlled = App.playerState.controlled_entities[0];
            const join = await fetch(`/api/sessions/${sessionId}/join`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({principal_id: principalId}),
            }).then(r => ({status: r.status, body: r.json()})).then(async x => ({status: x.status, body: await x.body}));
            const chat = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    campaign_id: campaignId,
                    session_id: sessionId,
                    speaker_entity_id: controlled.entity_id,
                    speaker_principal_id: principalId,
                    message: 'V1 golden path smoke',
                }),
            }).then(r => ({status: r.status, body: r.json()})).then(async x => ({status: x.status, body: await x.body}));
            const save = await fetch('/api/saves/game/export', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({campaign_id: campaignId, passphrase: 'v1-golden-path'}),
            });
            const saveText = await save.text();
            return {
                principalId,
                sessionId,
                campaignId,
                controlledId: controlled.entity_id,
                dmLeakText: document.body.innerText.includes('The bell is cursed') || document.body.innerText.includes('dm_only'),
                join,
                chat,
                saveStatus: save.status,
                savePrefix: saveText.slice(0, 12),
            };
        }"""
    )

    assert state["principalId"]
    assert state["sessionId"]
    assert state["controlledId"]
    assert state["join"]["status"] == 200
    assert state["join"]["body"]["joined"] is True
    assert state["chat"]["status"] == 200
    assert state["saveStatus"] == 200
    assert state["savePrefix"] == "ttdm-save:v1"
    assert state["dmLeakText"] is False

    page.reload()
    page.wait_for_function("window.__TTDM_PLAYER_STATE_LOADED === true", timeout=10000)
    resumed = page.evaluate(
        """() => ({
            principalId: App.principalId,
            sessionId: App.sessionId,
            controlled: (App.playerState.controlled_entities || []).map(e => e.entity_id),
        })"""
    )
    assert resumed["principalId"] == state["principalId"]
    assert resumed["sessionId"] == state["sessionId"]
    assert state["controlledId"] in resumed["controlled"]
