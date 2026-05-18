import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra/docker-compose.yml"


def _ensure_env_loaded() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        example = ROOT / ".env.example"
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_ensure_env_loaded()


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, env=os.environ.copy(), check=True)


@pytest.fixture(scope="session")
def integration_stack() -> Iterator[None]:
    if shutil.which("docker") is None:
        pytest.skip("docker is required for integration tests")

    _run([sys.executable, str(ROOT / "scripts" / "integration_boot.py")])

    try:
        yield
    finally:
        _run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"])


@pytest.fixture
def postgres_dsn() -> str:
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://tabletop:tabletop_dev_password@localhost:5432/tabletop_dm",
    )
