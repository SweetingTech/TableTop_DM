from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from infra.migrate import MigrationError, discover

pytestmark = pytest.mark.contracts
ROOT = Path(__file__).resolve().parents[2]


def _manage_module():
    spec = importlib.util.spec_from_file_location("tabletop_manage", ROOT / "scripts" / "manage.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_break_has_one_numbered_baseline() -> None:
    migrations = discover(ROOT / "infra" / "sql" / "migrations")
    assert [migration.version for migration in migrations] == ["001_simulation_kernel.sql"]
    assert not (ROOT / "infra" / "sql" / "init").exists()
    assert not (ROOT / "infra" / "sql" / "seed").exists()


def test_migration_discovery_rejects_gaps_and_unmanaged_sql(tmp_path: Path) -> None:
    (tmp_path / "002_gap.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="contiguous"):
        discover(tmp_path)
    (tmp_path / "notes.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="invalid migration filename"):
        discover(tmp_path)


def test_baseline_encodes_isolation_append_only_and_forced_rls() -> None:
    ddl = (ROOT / "infra" / "sql" / "migrations" / "001_simulation_kernel.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE sim.branch_projections" in ddl
    assert "FOREIGN KEY (world_id, branch_id, run_id)" in ddl
    assert "resulting_state_hash text NOT NULL" in ddl
    assert "PRIMARY KEY (branch_id, id)" in ddl
    assert "PRIMARY KEY (persona_id, version_id)" in ddl
    assert "parent_version_id uuid" in ddl
    assert "persona_version_id uuid" in ddl
    assert "UNIQUE (world_id, source_branch_id, through_event_seq, state_hash)" in ddl
    assert "CREATE TABLE population.lifecycle_transitions" in ddl
    assert "persistent_state jsonb NOT NULL" in ddl
    assert "compressed_state jsonb NOT NULL" in ddl
    assert "population_lifecycle_transitions_append_only" in ddl
    assert "GRANT INSERT ON sim.snapshots" in ddl
    assert "sim_command_log_append_only" in ddl
    assert "sim_events_append_only" in ddl
    assert "cognition_relationship_changes_append_only" in ddl
    assert "CREATE TABLE cognition.relationship_changes" in ddl
    assert "FOREIGN KEY (world_id, branch_id, source_event_id)" in ddl
    assert "experiments_telemetry_captures_immutable" in ddl
    assert "BEFORE UPDATE ON experiments.telemetry_captures" in ddl
    assert "GRANT INSERT, DELETE ON experiments.telemetry_captures" in ddl
    for table in (
        "sim.branch_projections",
        "sim.entities",
        "sim.command_log",
        "sim.events",
        "cognition.mind_states",
        "cognition.observations",
        "cognition.beliefs",
        "cognition.memories",
        "cognition.relationships",
        "cognition.relationship_changes",
        "cognition.runtime_assignments",
        "cognition.decision_traces",
        "experiments.telemetry_captures",
    ):
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in ddl
    assert "CHECK (NOT human_ground_truth_claimed)" in ddl


def test_compose_separates_migration_and_runtime_credentials() -> None:
    compose = yaml.safe_load((ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"postgres", "redis", "qdrant", "migrate", "app", "worker"} <= set(services)
    assert "DATABASE_ADMIN_URL" in services["migrate"]["environment"]
    assert "DATABASE_ADMIN_URL" not in services["app"]["environment"]
    assert "DATABASE_ADMIN_URL" not in services["worker"]["environment"]
    assert services["app"]["read_only"] is True
    assert services["worker"]["read_only"] is True
    assert services["worker"]["healthcheck"]["disable"] is True
    assert "build" in services["app"]
    assert "build" not in services["worker"]
    assert "build" not in services["migrate"]


def test_compose_publishes_only_loopback_and_requires_service_passwords() -> None:
    source = (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    compose = yaml.safe_load(source)
    services = compose["services"]
    for service_name in ("postgres", "redis", "qdrant", "app"):
        for published in services[service_name]["ports"]:
            assert "127.0.0.1" in published
    assert ":-postgres_dev_only" not in source
    assert ":-tabletop_runtime_dev_only" not in source
    assert ":-redis_dev_only" not in source
    assert "POSTGRES_PASSWORD is required" in source
    assert "APP_DATABASE_PASSWORD is required" in source
    assert "REDIS_PASSWORD is required" in source


def test_manager_generates_private_runtime_credentials_instead_of_copying_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manage = _manage_module()
    destination = tmp_path / ".env"
    monkeypatch.setattr(manage, "ENV_FILE", destination)
    monkeypatch.setattr(manage, "ENV_EXAMPLE", ROOT / ".env.example")

    manage.ensure_env()

    entries = manage._read_env(destination)
    assert entries["POSTGRES_PASSWORD"] != "postgres_dev_only"
    assert entries["APP_DATABASE_PASSWORD"] != "tabletop_runtime_dev_only"
    assert entries["REDIS_PASSWORD"] != "redis_dev_only"
    assert len(entries["TTDM_OPERATOR_TOKEN"]) >= 32
    assert entries["POSTGRES_PASSWORD"] in entries["DATABASE_ADMIN_URL"]
    assert entries["APP_DATABASE_PASSWORD"] in entries["DATABASE_URL"]
    assert entries["REDIS_PASSWORD"] in entries["REDIS_URL"]
    assert "127.0.0.1" in entries["DATABASE_ADMIN_URL"]
    assert "127.0.0.1" in entries["DATABASE_URL"]
    assert "127.0.0.1" in entries["REDIS_URL"]

    before = destination.read_text(encoding="utf-8")
    manage.ensure_env()
    assert destination.read_text(encoding="utf-8") == before


def test_manager_upgrades_a_legacy_env_for_the_hardened_v2_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manage = _manage_module()
    destination = tmp_path / ".env"
    destination.write_text(
        "POSTGRES_USER=postgres\n"
        "POSTGRES_PASSWORD=legacy-owner-password\n"
        "POSTGRES_DB=tabletop_dm\n"
        "POSTGRES_PORT=5432\n"
        "REDIS_PASSWORD=legacy-redis-password\n"
        "REDIS_PORT=6379\n"
        "DATABASE_URL=postgresql://postgres:legacy-owner-password@localhost:5432/tabletop_dm\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(manage, "ENV_FILE", destination)
    monkeypatch.setattr(manage, "ENV_EXAMPLE", ROOT / ".env.example")

    manage.ensure_env()

    entries = manage._read_env(destination)
    assert entries["POSTGRES_PASSWORD"] == "legacy-owner-password"
    assert entries["REDIS_PASSWORD"] == "legacy-redis-password"
    assert entries["APP_DATABASE_USER"] == "tabletop_runtime"
    assert len(entries["APP_DATABASE_PASSWORD"]) >= 32
    assert entries["APP_DATABASE_PASSWORD"] in entries["DATABASE_URL"]
    assert entries["POSTGRES_PASSWORD"] in entries["DATABASE_ADMIN_URL"]
    assert entries["REDIS_PASSWORD"] in entries["REDIS_URL"]
    assert len(entries["TTDM_OPERATOR_TOKEN"]) >= 32

    before = destination.read_text(encoding="utf-8")
    manage.ensure_env()
    assert destination.read_text(encoding="utf-8") == before


def test_manager_repairs_derived_urls_when_service_passwords_were_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manage = _manage_module()
    destination = tmp_path / ".env"
    destination.write_text(
        "POSTGRES_PASSWORD=\n"
        "APP_DATABASE_USER=tabletop_runtime\n"
        "APP_DATABASE_PASSWORD=runtime-password\n"
        "REDIS_PASSWORD=\n"
        "DATABASE_ADMIN_URL=postgresql://postgres:stale@localhost:5432/tabletop_dm\n"
        "REDIS_URL=redis://:stale@localhost:6379/0\n"
        "TTDM_OPERATOR_TOKEN=existing-operator-token\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(manage, "ENV_FILE", destination)
    monkeypatch.setattr(manage, "ENV_EXAMPLE", ROOT / ".env.example")

    manage.ensure_env()

    entries = manage._read_env(destination)
    assert entries["POSTGRES_PASSWORD"] in entries["DATABASE_ADMIN_URL"]
    assert entries["REDIS_PASSWORD"] in entries["REDIS_URL"]
    assert "stale" not in entries["DATABASE_ADMIN_URL"]
    assert "stale" not in entries["REDIS_URL"]
    assert "localhost" not in entries["DATABASE_ADMIN_URL"]
    assert "localhost" not in entries["REDIS_URL"]
    assert entries["TTDM_OPERATOR_TOKEN"] == "existing-operator-token"


def test_env_example_defaults_to_mock_and_telemetry_off() -> None:
    entries = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            entries[key] = value
    assert entries["TTDM_LLM_MODE"] == "mock"
    assert entries["TTDM_TELEMETRY_ENABLED"] == "0"
    assert "tabletop_runtime" in entries["DATABASE_URL"]
    assert "postgres@" not in entries["DATABASE_URL"]
    for key in ("DATABASE_ADMIN_URL", "DATABASE_URL", "REDIS_URL", "QDRANT_URL"):
        assert "127.0.0.1" in entries[key]


def test_ci_covers_backend_frontend_integration_image_and_user_journeys() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    e2e = (ROOT / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")
    assert "uv run ruff check ." in ci
    assert 'uv run pytest -m "unit or contracts"' in ci
    assert "npm --prefix frontend run test" in ci
    assert "npm --prefix frontend run build" in ci
    assert "uv run pytest -m integration" in ci
    assert "docker build --tag tabletop-dm-v2:ci ." in ci
    for watched_path in ("kernel/**", "frontend/**", "infra/**", "tests/e2e/**"):
        assert watched_path in e2e
    assert "uv run pytest -m e2e tests/e2e -v" in e2e
    assert "live-backend-release-screenshots" in e2e


def test_production_image_builds_frontend_and_runs_unprivileged() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22-alpine AS frontend-build" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=frontend-build" in dockerfile
    assert "USER tabletop" in dockerfile
    assert 'CMD ["python", "main.py", "serve"' in dockerfile
