"""Local pytest config for the Playwright e2e suite.

Sets sensible defaults so failures auto-capture artifacts (video, screenshot,
trace) without forcing every developer to remember the CLI flags. Explicit
CLI flags still override these defaults.

Artifacts land in ``test-results-e2e/`` at the repo root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.request

import pytest

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "test-results-e2e"
BASE_URL = os.environ.get("TTDM_BASE_URL", "http://localhost:8000").rstrip("/")
PREFLIGHT_PATHS = ("/health", "/readyz?verbose=1", "/")
CI_STRICT_E2E = os.environ.get("CI") and os.environ.get("TTDM_E2E_ALLOW_SKIP") != "1"

APP_FATAL_CONSOLE_MARKERS = (
    "Uncaught",
    "ReferenceError",
    "TypeError",
    "SyntaxError",
    "Tabletop DM",
    "TableTop DM",
    "TTDM",
)


def pytest_configure(config):
    """Apply opt-in artifact capture defaults for pytest-playwright."""
    # pytest-playwright registers these options; values mirror its choice list.
    defaults = {
        "video": "retain-on-failure",
        "screenshot": "only-on-failure",
        "tracing": "retain-on-failure",
        "output": str(ARTIFACT_DIR),
    }
    for name, value in defaults.items():
        # Only set when caller hasn't overridden via CLI/ini.
        current = getattr(config.option, name, None)
        if current in (None, "off", ""):
            setattr(config.option, name, value)


def _write_artifact(name: str, content: str) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / name).write_text(content, encoding="utf-8")


def _http_ok(path: str, timeout: float = 5.0) -> tuple[bool, str]:
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if path.startswith("/readyz"):
                _write_artifact("e2e-readyz.json", body)
            elif path == "/":
                _write_artifact("e2e-root-response.html", body)
            if 200 <= response.status < 300:
                return True, ""
            return False, f"{url} returned HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if path.startswith("/readyz"):
            _write_artifact("e2e-readyz.json", body)
            try:
                payload = json.loads(body)
                return False, f"{url} returned HTTP {exc.code}: {payload}"
            except json.JSONDecodeError:
                pass
        elif path == "/":
            _write_artifact("e2e-root-response.html", body)
        return False, f"{url} returned HTTP {exc.code}"
    except Exception as exc:
        return False, f"{url} is not ready: {exc}"


@pytest.fixture(scope="session", autouse=True)
def e2e_preflight():
    """Skip the suite cleanly when the already-running app is unavailable."""
    failures = []
    for path in PREFLIGHT_PATHS:
        ok, reason = _http_ok(path, timeout=10.0 if path.startswith("/readyz") else 5.0)
        if not ok:
            failures.append(reason)

    if failures:
        reason = (
            "Tabletop DM E2E preflight failed; start a ready app at "
            f"{BASE_URL}. " + " | ".join(failures)
        )
        if CI_STRICT_E2E:
            pytest.fail(reason)
        pytest.skip(reason)


def _is_app_owned_console_error(text: str) -> bool:
    if "Failed to load resource" in text:
        return False
    return any(marker in text for marker in APP_FATAL_CONSOLE_MARKERS)


@pytest.fixture(autouse=True)
def fail_on_app_console_errors(page):
    """Fail on app-owned fatal console errors without treating browser noise as fatal."""
    errors: list[str] = []

    def capture(msg):
        if msg.type == "error" and _is_app_owned_console_error(msg.text):
            errors.append(msg.text)

    page.on("console", capture)
    yield

    assert not errors, "App-owned console errors:\n" + "\n".join(errors)
