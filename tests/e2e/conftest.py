"""Local pytest config for the Playwright e2e suite.

Sets sensible defaults so failures auto-capture artifacts (video, screenshot,
trace) without forcing every developer to remember the CLI flags. Explicit
CLI flags still override these defaults.

Artifacts land in ``test-results-e2e/`` at the repo root.
"""
from __future__ import annotations

from pathlib import Path

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "test-results-e2e"


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
