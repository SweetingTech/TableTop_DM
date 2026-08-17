#!/usr/bin/env python3
"""Cross-platform lifecycle manager for the local v2 stack."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "docker-compose.yml"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


def _read_env(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            entries[key] = value
    return entries


def _render_env(template: str, replacements: dict[str, str]) -> str:
    rendered: list[str] = []
    seen: set[str] = set()
    for line in template.splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, _value = line.split("=", 1)
            if key in replacements:
                line = f"{key}={replacements[key]}"
                seen.add(key)
        rendered.append(line)
    for key in sorted(set(replacements) - seen):
        rendered.append(f"{key}={replacements[key]}")
    return "\n".join(rendered) + "\n"


def _write_private_env(contents: str) -> None:
    ENV_FILE.write_text(contents, encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def ensure_env() -> None:
    if ENV_FILE.exists():
        entries = _read_env(ENV_FILE)
        replacements: dict[str, str] = {}
        upgraded_runtime_login = False
        generated_owner_password = not entries.get("POSTGRES_PASSWORD", "").strip()
        if generated_owner_password:
            replacements["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
        if not entries.get("APP_DATABASE_USER", "").strip():
            replacements["APP_DATABASE_USER"] = "tabletop_runtime"
            upgraded_runtime_login = True
        if not entries.get("APP_DATABASE_PASSWORD", "").strip():
            replacements["APP_DATABASE_PASSWORD"] = secrets.token_urlsafe(32)
            upgraded_runtime_login = True
        generated_redis_password = not entries.get("REDIS_PASSWORD", "").strip()
        if generated_redis_password:
            replacements["REDIS_PASSWORD"] = secrets.token_urlsafe(32)
        generated_token = not entries.get("TTDM_OPERATOR_TOKEN", "").strip()
        if generated_token:
            replacements["TTDM_OPERATOR_TOKEN"] = secrets.token_urlsafe(32)

        resolved = {**entries, **replacements}
        postgres_user = resolved.get("POSTGRES_USER", "postgres")
        postgres_password = resolved["POSTGRES_PASSWORD"]
        postgres_db = resolved.get("POSTGRES_DB", "tabletop_dm")
        postgres_port = resolved.get("POSTGRES_PORT", "5432")
        runtime_user = resolved["APP_DATABASE_USER"]
        runtime_password = resolved["APP_DATABASE_PASSWORD"]
        redis_password = resolved["REDIS_PASSWORD"]
        redis_port = resolved.get("REDIS_PORT", "6379")
        if generated_owner_password or not entries.get("DATABASE_ADMIN_URL", "").strip():
            replacements["DATABASE_ADMIN_URL"] = (
                f"postgresql://{postgres_user}:{postgres_password}@127.0.0.1:"
                f"{postgres_port}/{postgres_db}"
            )
        if upgraded_runtime_login or not entries.get("DATABASE_URL", "").strip():
            replacements["DATABASE_URL"] = (
                f"postgresql://{runtime_user}:{runtime_password}@127.0.0.1:"
                f"{postgres_port}/{postgres_db}"
            )
        if generated_redis_password or not entries.get("REDIS_URL", "").strip():
            replacements["REDIS_URL"] = f"redis://:{redis_password}@127.0.0.1:{redis_port}/0"
        for key in ("DATABASE_ADMIN_URL", "DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
            value = replacements.get(key, entries.get(key, ""))
            normalized = value.replace("@localhost:", "@127.0.0.1:").replace(
                "//localhost:", "//127.0.0.1:"
            )
            if normalized != value:
                replacements[key] = normalized
        for key in ("REDIS_HOST", "QDRANT_HOST"):
            if entries.get(key, "").strip().lower() == "localhost":
                replacements[key] = "127.0.0.1"
        if not replacements:
            return
        _write_private_env(
            _render_env(
                ENV_FILE.read_text(encoding="utf-8"),
                replacements,
            )
        )
        print("updated v2 local credentials in .env")
        if generated_token:
            print(f"local operator token: {replacements['TTDM_OPERATOR_TOKEN']}")
        return

    template = ENV_EXAMPLE.read_text(encoding="utf-8")
    entries = _read_env(ENV_EXAMPLE)
    postgres_password = secrets.token_urlsafe(32)
    runtime_password = secrets.token_urlsafe(32)
    redis_password = secrets.token_urlsafe(32)
    operator_token = secrets.token_urlsafe(32)
    postgres_user = entries.get("POSTGRES_USER", "postgres")
    postgres_db = entries.get("POSTGRES_DB", "tabletop_dm")
    postgres_port = entries.get("POSTGRES_PORT", "5432")
    runtime_user = entries.get("APP_DATABASE_USER", "tabletop_runtime")
    redis_port = entries.get("REDIS_PORT", "6379")
    replacements = {
        "POSTGRES_PASSWORD": postgres_password,
        "APP_DATABASE_PASSWORD": runtime_password,
        "REDIS_PASSWORD": redis_password,
        "TTDM_OPERATOR_TOKEN": operator_token,
        "DATABASE_ADMIN_URL": (
            f"postgresql://{postgres_user}:{postgres_password}@127.0.0.1:"
            f"{postgres_port}/{postgres_db}"
        ),
        "DATABASE_URL": (
            f"postgresql://{runtime_user}:{runtime_password}@127.0.0.1:"
            f"{postgres_port}/{postgres_db}"
        ),
        "REDIS_URL": f"redis://:{redis_password}@127.0.0.1:{redis_port}/0",
    }
    _write_private_env(_render_env(template, replacements))
    print(f"created {ENV_FILE.name} with generated local credentials")
    print(f"local operator token: {operator_token}")


def show_operator_token(_: argparse.Namespace) -> None:
    ensure_env()
    token = _read_env(ENV_FILE).get("TTDM_OPERATOR_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TTDM_OPERATOR_TOKEN is missing from .env")
    print(token)


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    ensure_env()
    command = [
        "docker",
        "compose",
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(COMPOSE_FILE),
        *arguments,
    ]
    return subprocess.run(command, cwd=ROOT, check=check, text=True)


def wait_ready(url: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ready") is True:
                    return payload
                last_error = f"HTTP {response.status}: {payload}"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"stack did not become ready at {url}: {last_error}")


def start(args: argparse.Namespace) -> None:
    resolved_compose = COMPOSE_FILE.resolve()
    if ROOT not in resolved_compose.parents:
        raise RuntimeError(f"refusing to use compose file outside workspace: {resolved_compose}")
    compose("config", "--quiet")
    if args.reset:
        print("reset requested: deleting only tabletop-dm-v2 compose volumes")
        compose("down", "--volumes", "--remove-orphans")
    up = ["up", "-d"]
    if not args.no_build:
        up.append("--build")
    up.extend(("app", "worker"))
    compose(*up)
    payload = wait_ready(args.ready_url, args.timeout)
    print(json.dumps(payload, indent=2, sort_keys=True))


def stop(args: argparse.Namespace) -> None:
    command = ["down", "--remove-orphans"]
    if args.volumes:
        print("deleting only tabletop-dm-v2 compose volumes")
        command.append("--volumes")
    compose(*command)


def status(_: argparse.Namespace) -> None:
    compose("ps")


def migrate(_: argparse.Namespace) -> None:
    compose("run", "--rm", "migrate")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser(
        "start", help="build and start app, worker, and dependencies"
    )
    start_parser.add_argument(
        "--reset", action="store_true", help="delete this stack's data volumes first"
    )
    start_parser.add_argument("--no-build", action="store_true")
    start_parser.add_argument("--timeout", type=float, default=180)
    start_parser.add_argument("--ready-url", default="http://127.0.0.1:8000/readyz")
    start_parser.set_defaults(handler=start)

    stop_parser = subparsers.add_parser("stop", help="stop the local stack")
    stop_parser.add_argument(
        "--volumes", action="store_true", help="also delete this stack's data volumes"
    )
    stop_parser.set_defaults(handler=stop)

    status_parser = subparsers.add_parser("status")
    status_parser.set_defaults(handler=status)

    token_parser = subparsers.add_parser("token", help="print the generated local operator token")
    token_parser.set_defaults(handler=show_operator_token)

    migrate_parser = subparsers.add_parser("migrate")
    migrate_parser.set_defaults(handler=migrate)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        args.handler(args)
    except (RuntimeError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"lifecycle error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
