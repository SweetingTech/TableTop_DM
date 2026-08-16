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


def test_ci_workflow_does_not_require_openai_secrets() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" not in workflow
    assert "AI_INTEGRATIONS_OPENAI_API_KEY" not in workflow


def test_make_ci_integration_writes_skip_marker_when_docker_unavailable() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "scripts/docker_runtime_available.sh" in makefile
    assert "burn-bag/ci-integration-skipped.txt" in makefile
    assert "SKIP: Docker runtime unavailable; integration tests skipped" in makefile
