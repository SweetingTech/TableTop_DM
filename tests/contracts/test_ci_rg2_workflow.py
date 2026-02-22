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


def test_ci_workflow_does_not_require_openai_secrets() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" not in workflow
    assert "AI_INTEGRATIONS_OPENAI_API_KEY" not in workflow
