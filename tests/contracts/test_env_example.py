from __future__ import annotations

import re
from pathlib import Path


ENV_FILES = [
    Path("app.py"),
    *Path("services").rglob("*.py"),
    *Path("scripts").glob("*.py"),
    *Path("infra").glob("*.py"),
]

IGNORED_DYNAMIC = {
    "AUDIT_MODE_HINT",
    "CI",
    "TTDM_BASE_URL",
    "TTDM_E2E_ALLOW_SKIP",
    "VTT_HEALTH_URL",
}


def test_env_example_documents_runtime_environment_variables() -> None:
    example_keys = {
        line.split("=", 1)[0].strip()
        for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    referenced: set[str] = set()
    pattern = re.compile(
        r"os\.environ(?:\.get)?\([\"']([A-Z0-9_]+)[\"']|os\.getenv\([\"']([A-Z0-9_]+)[\"']"
    )
    for path in ENV_FILES:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            key = match.group(1) or match.group(2)
            if key and key not in IGNORED_DYNAMIC:
                referenced.add(key)

    missing = sorted(referenced - example_keys)
    assert missing == []
