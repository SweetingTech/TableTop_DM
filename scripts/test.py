#!/usr/bin/env python3
"""Cross-platform test lane dispatcher used by local scripts and CI."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, check=True, env=env)


def python_tests(marker: str, path: str = "tests") -> None:
    run(sys.executable, "-m", "pytest", "-m", marker, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "suite",
        nargs="?",
        default="fast",
        choices=("fast", "unit", "contracts", "integration", "e2e", "all"),
    )
    suite = parser.parse_args().suite
    try:
        if suite in {"fast", "all"}:
            run(sys.executable, "-m", "ruff", "check", ".")
            run(sys.executable, "-m", "ruff", "format", "--check", ".")
            python_tests("unit or contracts")
            run("npm", "--prefix", "frontend", "run", "lint")
            run("npm", "--prefix", "frontend", "run", "test")
            run("npm", "--prefix", "frontend", "run", "build")
        elif suite == "unit":
            python_tests("unit")
        elif suite == "contracts":
            python_tests("contracts")
        if suite in {"integration", "all"}:
            environment = os.environ.copy()
            environment["TTDM_INTEGRATION"] = "1"
            run(sys.executable, "-m", "pytest", "-m", "integration", env=environment)
        if suite in {"e2e", "all"}:
            python_tests("e2e", "tests/e2e")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"test lane failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
