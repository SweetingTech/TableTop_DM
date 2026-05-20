"""Playwright smoke tests for the landing-page guided tour.

Assumes the Flask app is already running at BASE_URL (default http://localhost:8000).
Run with:  pytest tests/e2e/test_landing_tour.py -v
"""

from __future__ import annotations

import os
import re
import time

import pytest
from playwright.sync_api import Error as PWError, Page, expect

BASE_URL = os.environ.get("TTDM_BASE_URL", "http://localhost:8000")
STORAGE_KEY = "ttdm_tour_done_v1"
pytestmark = pytest.mark.e2e


def _goto_with_retry(page: Page, url: str, attempts: int = 3) -> None:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            page.goto(url)
            return
        except PWError as e:
            last = e
            time.sleep(0.4)
    raise last  # type: ignore[misc]


@pytest.fixture(autouse=True)
def _fresh_tour(page: Page):
    """Use the deterministic dashboard test hook so every test starts the tour."""
    _goto_with_retry(page, f"{BASE_URL}/?tour=1")


def test_tour_auto_starts_on_first_visit(page: Page):
    overlay = page.locator(".tour-overlay")
    expect(overlay).to_have_class(re.compile(r"\bshow\b"), timeout=3000)

    tooltip = page.locator(".tour-tooltip")
    expect(tooltip).to_be_visible()
    expect(tooltip.locator("h4")).to_have_text("Welcome to Tabletop DM")
    expect(tooltip.locator(".tour-progress")).to_contain_text("Step 1 of 11")
    expect(tooltip.locator("[data-tour-next]")).to_have_text("Start tour")


def test_step2_highlights_new_campaign_button_and_pauses(page: Page):
    page.locator(".tour-tooltip [data-tour-next]").click()

    tooltip = page.locator(".tour-tooltip")
    expect(tooltip.locator("h4")).to_contain_text("Open the wizard")
    expect(tooltip.locator(".tour-progress")).to_contain_text("Step 2 of 11")
    nxt = tooltip.locator("[data-tour-next]")
    expect(nxt).to_be_disabled()
    expect(tooltip.locator(".tour-hint")).to_contain_text("Waiting for you to click")

    # Spotlight should now be positioned (not centered)
    spotlight = page.locator(".tour-spotlight")
    expect(spotlight).not_to_have_class(re.compile(r"\bcenter\b"))


def test_clicking_new_campaign_opens_wizard_and_advances_tour(page: Page):
    page.locator(".tour-tooltip [data-tour-next]").click()  # 1 -> 2
    page.locator("[data-open-wizard]").first.click()  # opens wizard, fires event

    expect(page.locator("#wizardModal")).to_have_class(
        re.compile(r"\bopen\b"), timeout=3000
    )

    tooltip = page.locator(".tour-tooltip")
    expect(tooltip.locator("h4")).to_have_text("Name your campaign", timeout=3000)
    expect(tooltip.locator(".tour-progress")).to_contain_text("Step 3 of 11")
    expect(page.locator("#wizName")).to_be_focused()


def test_skip_tour_hides_overlay_and_sets_flag(page: Page):
    page.locator(".tour-tooltip [data-tour-skip]").click()
    expect(page.locator(".tour-overlay")).not_to_have_class(re.compile(r"\bshow\b"))
    flag = page.evaluate(f"localStorage.getItem('{STORAGE_KEY}')")
    assert flag == "1"


def test_take_the_guided_tour_link_restarts(page: Page):
    page.locator(".tour-tooltip [data-tour-skip]").click()
    expect(page.locator(".tour-overlay")).not_to_have_class(re.compile(r"\bshow\b"))

    page.locator("[data-restart-tour]").first.click()
    expect(page.locator(".tour-overlay")).to_have_class(
        re.compile(r"\bshow\b"), timeout=2000
    )
    expect(page.locator(".tour-tooltip h4")).to_have_text("Welcome to Tabletop DM")


def test_local_ai_block_step_renders(page: Page):
    """Walk to step 4 (Local AI auto-detect) and assert the spotlight finds the block."""
    page.locator(".tour-tooltip [data-tour-next]").click()  # 1 -> 2
    page.locator("[data-open-wizard]").first.click()  # opens wizard, 2 -> 3
    expect(page.locator(".tour-tooltip h4")).to_have_text(
        "Name your campaign", timeout=3000
    )

    page.locator(".tour-tooltip [data-tour-next]").click()  # 3 -> 4
    tooltip = page.locator(".tour-tooltip")
    expect(tooltip.locator("h4")).to_have_text("Local AI auto-detect")
    expect(tooltip.locator(".tour-progress")).to_contain_text("Step 4 of 11")
    expect(page.locator("#wizLocalAI")).to_be_visible()
