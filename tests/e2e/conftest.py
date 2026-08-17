from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "test-results-e2e"
BASE_URL = os.environ.get("TTDM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CI_STRICT = bool(os.environ.get("CI")) and os.environ.get("TTDM_E2E_ALLOW_SKIP") != "1"


def pytest_configure(config) -> None:
    defaults = {
        "video": "retain-on-failure",
        "screenshot": "only-on-failure",
        "tracing": "retain-on-failure",
        "output": str(ARTIFACT_DIR),
    }
    for name, value in defaults.items():
        if getattr(config.option, name, None) in (None, "", "off"):
            setattr(config.option, name, value)


def _request(path: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=10) as response:
            body = response.read().decode("utf-8", errors="replace")
            if path == "/readyz":
                ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
                (ARTIFACT_DIR / "readyz.json").write_text(body, encoding="utf-8")
                payload = json.loads(body)
                return response.status == 200 and payload.get("ready") is True, body
            return 200 <= response.status < 400, body
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return False, str(exc)


@pytest.fixture(scope="session", autouse=True)
def e2e_preflight() -> None:
    failures = []
    for path in ("/healthz", "/readyz", "/v2"):
        ok, detail = _request(path)
        if not ok:
            failures.append(f"{path}: {detail}")
    if failures:
        message = f"v2 application is not ready at {BASE_URL}: " + " | ".join(failures)
        if CI_STRICT:
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(autouse=True)
def operator_session_token(page) -> None:
    """Authenticate browser API calls without weakening the remote boundary."""
    token = os.environ.get("TTDM_OPERATOR_TOKEN", "")
    if token:
        page.add_init_script(
            f"sessionStorage.setItem('ttdm.v2.operator-token', {json.dumps(token)});"
        )


@pytest.fixture(autouse=True)
def no_browser_runtime_errors(page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))

    def on_console(message) -> None:
        if message.type == "error" and "favicon" not in message.text.lower():
            errors.append(f"console: {message.text}")

    page.on("console", on_console)
    yield
    assert not errors, "browser runtime errors:\n" + "\n".join(errors)
