"""Playwright smoke coverage for the documented GUI entry points."""

from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("TTDM_BASE_URL", "http://localhost:8000")

pytestmark = pytest.mark.e2e


def test_dashboard_exposes_primary_routes(page: Page):
    page.goto(f"{BASE_URL}/")

    expect(page).to_have_title(re.compile(r"Tabletop DM.*Dashboard", re.I))
    expect(page.get_by_role("link", name="Game Console", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Control Plane", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Help", exact=True)).to_be_visible()
    expect(
        page.get_by_role("heading", name=re.compile(r"Tabletop DM", re.I))
    ).to_be_visible()


@pytest.mark.parametrize(
    ("path", "title", "markers"),
    [
        ("/game", r"Tabletop DM.*Game Console", ("Control Plane", "Help")),
        (
            "/control",
            r"Tabletop DM.*Control Plane",
            ("Dashboard", "Game Console", "Help"),
        ),
        (
            "/help",
            r"TableTop DM.*Help",
            ("Dashboard", "Game Console", "Control Plane", "Documentation"),
        ),
    ],
)
def test_primary_route_loads_with_navigation(
    page: Page,
    path: str,
    title: str,
    markers: tuple[str, ...],
):
    page.goto(f"{BASE_URL}{path}")

    expect(page).to_have_title(re.compile(title, re.I))
    for marker in markers:
        expect(page.get_by_text(marker, exact=False).first).to_be_visible()
