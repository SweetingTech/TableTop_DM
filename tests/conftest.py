import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra/docker-compose.yml"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


@pytest.fixture(scope="session")
def integration_stack() -> Iterator[None]:
    env_path = ROOT / ".env"

    if shutil.which("docker") is None:
        pytest.skip("docker is required for integration tests")

    if not env_path.exists():
        example = ROOT / ".env.example"
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    _run(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"])
    _run(["bash", "-lc", "./infra/scripts/db_reset.sh"])
    _run(["bash", "-lc", "./infra/scripts/migrate.sh"])
    _run(["bash", "-lc", "./infra/scripts/seed_demo.sh"])

    try:
        yield
    finally:
        _run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"])


@pytest.fixture
def postgres_dsn() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql://tabletop:tabletop_dev_password@localhost:5432/tabletop_dm",
    )
