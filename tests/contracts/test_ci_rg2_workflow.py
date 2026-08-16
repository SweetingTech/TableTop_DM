import runpy
from pathlib import Path

import pytest

pytestmark = pytest.mark.contracts


def test_ci_jobs_enable_mock_llm_and_seeded_rng() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "TTDM_LLM_MODE: mock" in workflow
    assert 'TTDM_RNG_SEED: "1337"' in workflow


def test_ci_integration_job_runs_infra_migrate_seed_and_smoke() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "docker compose -f infra/docker-compose.yml up -d" in workflow
    assert "bash infra/scripts/compose_smoke.sh" in workflow
    assert "run: make ci-integration" in workflow


def test_compose_smoke_uses_qdrant_http_readiness() -> None:
    smoke = Path("infra/scripts/compose_smoke.sh").read_text(encoding="utf-8")

    assert 'curl -fsS "http://localhost:${QDRANT_HTTP_PORT:-6333}/healthz"' in smoke
    assert "State.Health.Status}}' tabletop_qdrant" not in smoke


def test_integration_reset_waits_for_container_health() -> None:
    reset_script = Path("scripts/db_reset.py").read_text(encoding="utf-8")

    assert 'docker_compose("up", "-d", "--wait")' in reset_script


def test_postgres_readiness_ignores_entrypoint_temporary_server() -> None:
    compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
    shell_scripts = [
        Path("scripts/start.sh"),
        Path("infra/scripts/migrate.sh"),
        Path("infra/scripts/seed_demo.sh"),
    ]
    integration_helpers = Path("scripts/integration_common.py").read_text(
        encoding="utf-8"
    )

    assert "pg_isready -h 127.0.0.1" in compose
    for script in shell_scripts:
        assert "pg_isready -h 127.0.0.1" in script.read_text(encoding="utf-8")
    assert (
        '"pg_isready",\n            "-h",\n            "127.0.0.1"'
        in integration_helpers
    )


def test_readiness_audit_uses_current_release_checklist() -> None:
    audit_module = runpy.run_path("scripts/audit_todo.py", run_name="audit_todo_test")
    checklist = Path(audit_module["DEFAULT_CHECKLIST_PATH"])

    assert checklist.is_file()
    assert audit_module["release_checklist_missing_headings"](checklist) == set()


def test_ci_workflow_does_not_require_openai_secrets() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" not in workflow
    assert "AI_INTEGRATIONS_OPENAI_API_KEY" not in workflow


def test_make_ci_integration_writes_skip_marker_when_docker_unavailable() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "scripts/docker_runtime_available.sh" in makefile
    assert "burn-bag/ci-integration-skipped.txt" in makefile
    assert "SKIP: Docker runtime unavailable; integration tests skipped" in makefile
