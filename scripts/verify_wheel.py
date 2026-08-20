#!/usr/bin/env python3
"""Verify a wheel contains and can load every non-Python runtime asset."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED_MEMBERS = (
    "persona/schema/core/dimensions.yaml",
    "persona/schema/world/dimensions.yaml",
    "persona/schema/tabletop/dimensions.yaml",
    "persona/schema/accessibility/dimensions.yaml",
    "infra/sql/migrations/001_simulation_kernel.sql",
    "infra/sql/migrations/002_identity_and_tabletop_workspaces.sql",
    "static/v2/index.html",
)


def verify_contents(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
        missing = [member for member in REQUIRED_MEMBERS if member not in members]
        if missing:
            raise RuntimeError(f"wheel is missing runtime assets: {missing}")
        if not any(
            re.fullmatch(r"static/v2/assets/index-[A-Za-z0-9_-]+\.js", member) for member in members
        ):
            raise RuntimeError("wheel is missing the compiled SPA entry module")


def verify_extracted_runtime(wheel: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="tabletop-dm-wheel-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(root)
        for key in (
            "DATABASE_URL",
            "REDIS_URL",
            "QDRANT_URL",
            "TTDM_OPERATOR_TOKEN",
        ):
            environment.pop(key, None)
        smoke = """
import re
from pathlib import Path
from infra.migrate import DEFAULT_MIGRATIONS_DIR, discover
from kernel.api.app import create_app
from persona.registry import PersonaSchemaRegistry

assert len(PersonaSchemaRegistry.load_default().dimensions) == 80
assert [item.version for item in discover(DEFAULT_MIGRATIONS_DIR)] == [
    "001_simulation_kernel.sql",
    "002_identity_and_tabletop_workspaces.sql",
]
app = create_app(artifact_root=Path("artifacts"))
client = app.test_client()
index = client.get("/v2/game")
assert index.status_code == 200
entry = re.search(rb'src="(/static/v2/assets/index-[^"]+\\.js)"', index.data)
assert entry is not None
asset = client.get(entry.group(1).decode())
assert asset.status_code == 200
assert "javascript" in asset.content_type
"""
        subprocess.run(
            [sys.executable, "-c", smoke],
            cwd=root,
            env=environment,
            check=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error(f"not a wheel file: {wheel}")
    verify_contents(wheel)
    verify_extracted_runtime(wheel)
    print(f"wheel runtime assets verified: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
