"""E2E smoke for /game booting from the authoritative player_state snapshot."""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("TTDM_BASE_URL", "http://localhost:8000")
PLAYER_A_ID = "22222222-2222-2222-2222-222222222222"
DM_ID = "22222222-2222-2222-2222-222222222221"

pytestmark = pytest.mark.e2e


def test_game_boot_uses_player_state_snapshot_and_survives_reload(page: Page):
    player_state_calls: list[str] = []
    page.on(
        "request",
        lambda request: player_state_calls.append(request.url)
        if "/api/sessions/" in request.url and "/player_state" in request.url
        else None,
    )

    page.goto(f"{BASE_URL}/game?principal_id={PLAYER_A_ID}")
    page.wait_for_function("App?.playerState?.principal?.role === 'PLAYER'", timeout=10000)

    first = page.evaluate(
        """() => ({
            principal: App?.playerState?.principal?.principal_id,
            controlled: (App?.playerState?.controlled_entities || []).map(e => e.entity_id),
            commandLocked: App?.playerState?.ui_state?.command_locked,
            eventCursor: App?.playerState?.visible_world?.event_cursor,
        })"""
    )

    assert player_state_calls
    assert first["principal"]
    assert first["controlled"]
    assert first["commandLocked"] is False
    assert "last_sequence" in first["eventCursor"]
    expect(page.locator("#principalName")).not_to_have_text("--")

    page.reload()
    page.wait_for_function("App?.playerState?.principal?.role === 'PLAYER'", timeout=10000)
    second = page.evaluate(
        """() => ({
            principal: App?.playerState?.principal?.principal_id,
            controlled: (App?.playerState?.controlled_entities || []).map(e => e.entity_id),
        })"""
    )

    assert second == {"principal": first["principal"], "controlled": first["controlled"]}


def test_player_game_hides_identity_switcher_and_dm_controls(page: Page):
    page.goto(f"{BASE_URL}/game?principal_id={PLAYER_A_ID}")
    page.wait_for_function("App?.playerState?.principal?.role === 'PLAYER'", timeout=10000)

    role = page.evaluate("() => App?.playerState?.principal?.role")
    assert role == "PLAYER"
    expect(page.locator("#principalSelect")).to_be_hidden()
    expect(page.get_by_role("button", name="Start Encounter")).to_be_hidden()
    expect(page.get_by_role("button", name="Advance Initiative")).to_be_hidden()
    expect(page.get_by_role("button", name="AI Narration")).to_be_hidden()


def test_gm_game_keeps_identity_inspection_and_dm_controls(page: Page):
    page.goto(f"{BASE_URL}/game?principal_id={DM_ID}")
    page.wait_for_function("App?.playerState?.principal?.role === 'GM'", timeout=10000)

    expect(page.locator("#principalSelect")).to_be_visible()
    expect(page.get_by_role("button", name="Start Encounter")).to_be_visible()
    expect(page.get_by_role("button", name="Advance Initiative")).to_be_visible()
    expect(page.get_by_role("button", name="AI Narration")).to_be_visible()


def test_game_refetches_player_state_on_event_cursor_gap(page: Page):
    player_state_calls: list[str] = []
    page.on(
        "request",
        lambda request: player_state_calls.append(request.url)
        if "/api/sessions/" in request.url and "/player_state" in request.url
        else None,
    )

    page.goto(f"{BASE_URL}/game?principal_id={PLAYER_A_ID}")
    page.wait_for_function("App?.playerState?.principal?.role === 'PLAYER'", timeout=10000)
    page.wait_for_function("App.lastEventSequence !== undefined", timeout=10000)

    initial_calls = len(player_state_calls)
    page.evaluate(
        """() => {
            App.lastEventSequence = 10;
            App.addEvent({event_id: 'gap-event', seq_id: 12, type: 'NARRATION', payload: {message: 'gap'}});
        }"""
    )
    page.wait_for_function(
        f"""() => performance.getEntriesByType('resource')
            .filter(e => e.name.includes('/api/sessions/') && e.name.includes('/player_state')).length > {initial_calls}""",
        timeout=10000,
    )
    assert len(player_state_calls) > initial_calls


def test_game_ignores_duplicate_realtime_events(page: Page):
    page.goto(f"{BASE_URL}/game?principal_id={PLAYER_A_ID}")
    page.wait_for_function("App?.playerState?.principal?.role === 'PLAYER'", timeout=10000)

    before = page.locator("#eventFeed .event-item").count()
    page.evaluate(
        """() => {
            const nextSeq = (App.lastEventSequence ?? 0) + 1;
            App.addEvent({event_id: 'dup-event', seq_id: nextSeq, type: 'NARRATION', payload: {message: 'only once'}});
            App.addEvent({event_id: 'dup-event', seq_id: nextSeq, type: 'NARRATION', payload: {message: 'only once'}});
        }"""
    )
    expect(page.locator("#eventFeed")).to_contain_text("only once")
    after = page.locator("#eventFeed .event-item").count()
    assert after == before + 1
