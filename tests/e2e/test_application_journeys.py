from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.e2e
BASE_URL = os.environ.get("TTDM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "test-results-e2e" / "release-screenshots"


def test_v2_shell_redirects_and_exposes_every_studio(page: Page) -> None:
    page.goto(f"{BASE_URL}/v2")
    expect(page).to_have_url(re.compile(r"/v2/game/?$"))
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    for label in (
        "Game Console",
        "Player Dashboard",
        "Dungeon Master",
        "Admin Dashboard",
        "Control Plane",
        "Persona Studio",
        "Population Studio",
        "Scenario Lab",
        "Run Inspector",
        "Calibration",
        "Settings",
    ):
        expect(page.get_by_role("link", name=label, exact=True)).to_be_visible()


def test_fresh_browser_session_opens_the_account_login(browser: Browser) -> None:
    # This context deliberately bypasses the suite's compatibility fixture,
    # matching a human opening the managed stack for the first time.
    context = browser.new_context()
    fresh_page = context.new_page()
    try:
        fresh_page.goto(f"{BASE_URL}/v2")
        expect(fresh_page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
        expect(fresh_page.get_by_label("Username")).to_have_value("admin")
        expect(fresh_page.get_by_text(re.compile(r"admin123"))).to_be_visible()
        expect(fresh_page.get_by_text("Local engine ready", exact=True)).to_have_count(0)
        expect(fresh_page.get_by_text(re.compile(r"operator token", re.I))).to_have_count(0)
    finally:
        context.close()


@pytest.mark.parametrize(
    ("test_id", "path", "heading"),
    (
        ("nav-game", "game", "Game Console"),
        ("nav-player", "player", "Player Dashboard"),
        ("nav-dm", "dm", "Dungeon Master"),
        ("nav-admin", "admin", "Admin Dashboard"),
        ("nav-control", "control", "Control Plane"),
        ("nav-personas", "personas", "Persona Studio"),
        ("nav-populations", "populations", "Population Studio"),
        ("nav-scenarios", "scenarios", "Scenario Lab"),
        ("nav-runs", "runs", "Run Inspector"),
        ("nav-calibration", "calibration", "Calibration"),
        ("nav-settings", "settings", "Settings"),
    ),
)
def test_navigation_is_url_addressable(page: Page, test_id: str, path: str, heading: str) -> None:
    page.goto(f"{BASE_URL}/v2/game")
    page.get_by_test_id(test_id).click()
    expect(page).to_have_url(re.compile(rf"/v2/{path}/?$"))
    expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()


def test_operator_can_create_world_and_generate_valid_persona(page: Page) -> None:
    world_name = f"Playwright World {uuid.uuid4().hex[:8]}"
    page.goto(f"{BASE_URL}/v2/control")
    page.get_by_test_id("world-name").fill(world_name)
    page.get_by_role("button", name="Create world", exact=True).click()
    expect(page.get_by_test_id("world-list")).to_contain_text(world_name)

    page.get_by_test_id("nav-personas").click()
    page.get_by_test_id("persona-seed").fill("4815162342")
    page.get_by_role("button", name="Generate persona", exact=True).click()
    expect(page.get_by_test_id("persona-validation")).to_contain_text(re.compile(r"valid", re.I))
    page.get_by_role("button", name="Compile persona", exact=True).click()
    expect(page.get_by_test_id("persona-result")).to_be_visible()


def test_control_plane_builds_a_scoped_world_and_isolated_trial_branch(page: Page) -> None:
    suffix = uuid.uuid4().hex[:8]
    world_name = f"Operator World {suffix}"
    actor_name = f"Guide {suffix}"
    entity_name = f"Quartermaster {suffix}"
    page.goto(f"{BASE_URL}/v2/control")

    page.get_by_test_id("world-name").fill(world_name)
    page.get_by_role("button", name="Create world", exact=True).click()
    expect(page.get_by_test_id("world-list")).to_contain_text(world_name)
    active_world = page.get_by_label("Active world")
    expect(active_world.locator("option", has_text=world_name)).to_have_count(1)
    active_world.select_option(label=world_name)
    expect(page.locator(".control-primary .panel-meta")).to_contain_text(world_name)

    # A live run supplies the command lineage for the typed entity creation.
    page.get_by_role("tab", name="Runs", exact=True).click()
    page.get_by_role("button", name="Start run", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("live run created")
    expect(page.locator(".control-primary")).to_contain_text("LIVE")

    page.get_by_role("tab", name="Actors & Capabilities", exact=True).click()
    page.get_by_label("Display name").fill(actor_name)
    page.get_by_role("button", name="Create actor", exact=True).click()
    expect(page.locator(".control-primary")).to_contain_text(actor_name)

    page.get_by_role("tab", name="Entities", exact=True).click()
    page.get_by_label("Entity name").fill(entity_name)
    page.get_by_label("Controller").select_option(label=actor_name)
    page.get_by_label("Grid X").fill("7")
    page.get_by_label("Grid Y").fill("4")
    page.get_by_role("button", name="Create entity", exact=True).click()
    expect(page.locator(".control-primary")).to_contain_text(entity_name)
    expect(page.locator(".control-primary")).to_contain_text("(7, 4)")

    page.get_by_role("tab", name="Snapshots", exact=True).click()
    page.get_by_role("button", name="Capture snapshot", exact=True).click()
    expect(page.locator(".control-primary tbody tr")).to_have_count(1)
    expect(page.locator(".control-primary")).to_contain_text("Snapshot")

    page.get_by_role("tab", name="Branches", exact=True).click()
    page.get_by_role("button", name="Create trial branch", exact=True).click()
    expect(page.locator(".control-primary")).to_contain_text("TRIAL")
    expect(page.locator(".control-primary tbody tr")).to_have_count(2)


def test_game_console_commits_and_reloads_a_live_ledger_event(page: Page) -> None:
    message = f"Release gate dialogue {uuid.uuid4().hex[:10]}"
    page.goto(f"{BASE_URL}/v2/game")
    expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
    expect(page.get_by_test_id("demo-mode-banner")).to_have_count(0)
    page.get_by_label("Command or dialogue").fill(message)
    page.get_by_role("button", name="Send proposal", exact=True).click()
    expect(page.get_by_text(message, exact=True)).to_be_visible()

    # Reloading proves this came back from the durable ledger rather than only
    # from the component's optimistic local event list.
    page.reload()
    expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
    expect(page.get_by_test_id("demo-mode-banner")).to_have_count(0)
    expect(page.get_by_text(message, exact=True)).to_be_visible()


def test_game_console_commits_a_typed_move_and_reloads_the_new_position(page: Page) -> None:
    page.goto(f"{BASE_URL}/v2/game")
    expect(page.get_by_role("heading", name="Game Console", exact=True)).to_be_visible()
    expect(page.get_by_test_id("demo-mode-banner")).to_have_count(0)

    actor = page.get_by_label("Acting entity")
    actor.select_option(label="Aster Vale")
    detail = page.locator(".entity-detail")
    before_match = re.search(r"Location\s*\((-?\d+),\s*(-?\d+)\)", detail.inner_text())
    assert before_match, f"Aster's starting location was not rendered: {detail.inner_text()}"
    before = (int(before_match.group(1)), int(before_match.group(2)))

    page.get_by_label("Command or dialogue").fill("/move west")
    with page.expect_response(
        lambda response: (
            response.request.method == "POST" and response.url.endswith("/api/v2/commands")
        )
    ) as response_info:
        page.get_by_role("button", name="Send proposal", exact=True).click()
    response = response_info.value
    assert response.ok, response.text()
    payload = response.json()
    assert payload["event"]["event_type"] == "tabletop.spatial.move"
    assert payload["result"]["result"]["destination"] == {
        "x": before[0] - 1,
        "y": before[1],
    }
    expect(page.locator(".event-panel")).to_contain_text("tabletop.spatial.move")

    # The canonical projection and typed ledger event both survive a page reload.
    page.reload()
    actor = page.get_by_label("Acting entity")
    actor.select_option(label="Aster Vale")
    detail = page.locator(".entity-detail")
    expect(detail).to_contain_text(f"({before[0] - 1}, {before[1]})")
    expect(page.locator(".event-panel")).to_contain_text("tabletop.spatial.move")


def test_population_scenario_and_run_inspection_flow(page: Page) -> None:
    page.goto(f"{BASE_URL}/v2/populations")
    page.get_by_test_id("population-name").fill(f"QA Cohort {uuid.uuid4().hex[:6]}")
    page.get_by_test_id("population-size").fill("12")
    page.get_by_role("button", name="Generate population", exact=True).click()
    page.get_by_role("button", name="Sample cohort", exact=True).click()
    expect(page.get_by_test_id("cohort-results")).to_be_visible()

    page.get_by_test_id("nav-scenarios").click()
    page.get_by_role("button", name="Run scenario", exact=True).click()
    expect(page.get_by_test_id("scenario-results")).to_be_visible(timeout=60_000)

    page.get_by_test_id("nav-runs").click()
    expect(page.get_by_test_id("run-list")).to_be_visible()
    expect(page.get_by_test_id("run-inspector")).to_be_visible()
    page.get_by_role("tab", name="Decisions", exact=True).click()
    expect(page.locator(".decision-list article").first).to_be_visible(timeout=30_000)
    expect(page.locator(".run-inspector-panel")).not_to_contain_text("No decision trace")


def test_run_inspector_reopens_durable_job_history(page: Page) -> None:
    page.goto(f"{BASE_URL}/v2/runs")
    run_list = page.get_by_test_id("run-list")
    rows = run_list.locator(".selection-row")
    expect(rows.first).to_be_visible(timeout=30_000)
    expected_job_id = os.environ.get("TTDM_EXPECTED_JOB_ID", "").strip()
    selected = rows.filter(has_text=expected_job_id).first if expected_job_id else rows.first
    expect(selected).to_be_visible()
    selected.click()
    expect(page.get_by_test_id("run-inspector")).to_be_visible()
    expect(page.get_by_test_id("demo-mode-banner")).to_have_count(0)
    if expected_job_id:
        expect(run_list).to_contain_text(expected_job_id)
        expect(page.locator(".run-detail")).not_to_contain_text("No trial selected", timeout=30_000)
        expect(page.locator(".run-inspector-panel")).not_to_contain_text(
            "No decision trace", timeout=30_000
        )
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(SCREENSHOT_DIR / "desktop-runs-after-restart.png"),
            full_page=True,
        )


def test_calibration_requires_review_before_separate_policy_promotion(page: Page) -> None:
    page.goto(f"{BASE_URL}/v2/calibration")
    expect(page.get_by_test_id("demo-mode-banner")).to_have_count(0)
    version = uuid.uuid4().hex[:10]
    page.get_by_label("Policy version").fill(f"onboarding-policy-e2e-{version}")
    page.get_by_label("Human evidence version").fill(f"playwright-evidence-{version}")

    page.get_by_role("button", name="Compare evidence", exact=True).click()
    review_package = page.locator(".calibration-review")
    expect(review_package.get_by_text("REVIEW REQUIRED", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Approve proposal", exact=True)).to_be_enabled()
    expect(page.get_by_role("button", name="Promote policy", exact=True)).to_be_disabled()

    page.get_by_role("button", name="Approve proposal", exact=True).click()
    expect(review_package.get_by_text("APPROVED", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Proposal reviewed", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Promote policy", exact=True)).to_be_enabled()

    page.get_by_role("button", name="Promote policy", exact=True).click()
    expect(review_package.get_by_text("PROMOTED", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Policy promoted", exact=True)).to_be_disabled()
    expect(review_package).to_contain_text("Local operator")


def test_telemetry_requires_explicit_operator_opt_in(page: Page) -> None:
    page.goto(f"{BASE_URL}/v2/settings")
    toggle = page.get_by_role("checkbox", name="Human telemetry", exact=True)
    expect(toggle).not_to_be_checked()
    toggle.check()
    expect(toggle).to_be_checked()
    expect(page.get_by_role("status")).to_contain_text("Local human telemetry enabled.")
    toggle.uncheck()
    expect(toggle).not_to_be_checked()
    expect(page.get_by_role("status")).to_contain_text("Human telemetry disabled.")


def test_capture_live_backend_desktop_and_mobile_release_views(page: Page) -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    routes = (
        ("game", "Game Console"),
        ("player", "Player Dashboard"),
        ("dm", "Dungeon Master"),
        ("admin", "Admin Dashboard"),
        ("control", "Control Plane"),
        ("personas", "Persona Studio"),
        ("populations", "Population Studio"),
        ("scenarios", "Scenario Lab"),
        ("runs", "Run Inspector"),
        ("calibration", "Calibration"),
        ("settings", "Settings"),
    )
    for profile, viewport in (
        ("desktop", {"width": 1440, "height": 1000}),
        ("mobile", {"width": 390, "height": 844}),
    ):
        page.set_viewport_size(viewport)
        for path, heading in routes:
            page.goto(f"{BASE_URL}/v2/{path}")
            expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()
            expect(page.get_by_test_id("demo-mode-banner")).to_have_count(0)
            if profile == "mobile":
                overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                assert overflow <= 1, f"{path} has {overflow}px horizontal overflow"
            page.screenshot(
                path=str(SCREENSHOT_DIR / f"{profile}-{path}.png"),
                full_page=True,
            )
