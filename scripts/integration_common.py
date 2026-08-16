"""Shared helpers for cross-platform integration scripts."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"


def ensure_env_file() -> None:
    if not ENV_FILE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")


def load_env() -> dict[str, str]:
    ensure_env_file()
    values: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    env = os.environ.copy()
    env.update(values)
    return env


def run(
    command: list[str],
    *,
    input_text: str | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    env = load_env()
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        check=check,
    )


def docker_compose(
    *args: str,
    input_text: str | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        input_text=input_text,
        capture=capture,
        check=check,
    )


def psql(
    *args: str, sql: str | None = None, capture: bool = False
) -> subprocess.CompletedProcess:
    env = load_env()
    return docker_compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        env.get("POSTGRES_USER", "postgres"),
        "-d",
        env.get("POSTGRES_DB", "tabletop_dm"),
        *args,
        input_text=sql,
        capture=capture,
    )


def wait_for_postgres(timeout_seconds: int = 60) -> None:
    env = load_env()
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        result = docker_compose(
            "exec",
            "-T",
            "postgres",
            "pg_isready",
            "-U",
            env.get("POSTGRES_USER", "postgres"),
            "-d",
            env.get("POSTGRES_DB", "tabletop_dm"),
            capture=True,
            check=False,
        )
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout or "").strip()
        time.sleep(1)
    raise RuntimeError(
        f"postgres did not become ready within {timeout_seconds}s: {last_error}"
    )
