from __future__ import annotations

import uuid

import pytest

from experiments.jobs import JobManager
from experiments.models import JobRecord
from kernel.api.app import create_app

pytestmark = pytest.mark.unit


def test_generic_scenario_executes_typed_trial_branches_and_rehydrates_history(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(artifact_root=tmp_path)
    simulation = app.extensions["simulation"]
    demo = app.extensions["demo_ids"]
    canonical = simulation.states.get(demo["branch_id"])
    canonical_before = canonical.state_hash
    definition = {
        "scenario_id": "market-tax",
        "version": "1.0.0",
        "name": "Market tax counterfactual",
        "cohort_size": 2,
        "seeds": [17],
        "intervention": {
            "type": "SET_MARKET_TAX",
            "deltas": [
                {
                    "projection": "tabletop.economy",
                    "operation": "SET",
                    "values": {"tax_percent": 15},
                }
            ],
        },
    }
    with app.test_client() as client:
        assert client.post("/api/v2/scenarios", json=definition).status_code == 201
        launched = client.post(
            "/api/v2/scenarios/market-tax/run",
            json={"cohort_size": 2, "seeds": [17], "include_trials": 2},
        )
    assert launched.status_code == 201
    payload = launched.get_json()
    assert payload["job"]["status"] == "COMPLETED"
    assert payload["report"]["trial_count"] == 2
    assert payload["report"]["canonical_world_unchanged"] is True
    trial = payload["report"]["sample_trials"][0]
    assert trial["events"][0]["event_type"] == "experiments.scenario.apply"
    assert trial["events"][0]["persona_version"]
    assert uuid.UUID(trial["events"][0]["event_id"]) in simulation.events
    trial_state = simulation.states.get(uuid.UUID(trial["branch_id"]))
    assert trial_state.projections["tabletop.economy"]["singleton"] == {"tax_percent": 15}
    assert canonical.state_hash == canonical_before

    report_id = payload["report_id"]
    job_id = payload["job"]["job_id"]
    trial_id = trial["trial_id"]
    restarted = create_app(artifact_root=tmp_path)
    with restarted.test_client() as client:
        scenarios = client.get("/api/v2/scenarios").get_json()
        restored_job = client.get(f"/api/v2/jobs/{job_id}")
        restored_report = client.get(f"/api/v2/reports/{report_id}")
        restored_trial = client.get(f"/api/v2/trials/{trial_id}")
        idempotent_launch = client.post(
            "/api/v2/scenarios/market-tax/run",
            json={"cohort_size": 2, "seeds": [17], "include_trials": 2},
        )
    assert any(item["scenario_id"] == "market-tax" for item in scenarios)
    assert restored_job.get_json()["status"] == "COMPLETED"
    assert restored_report.get_json()["scenario_id"] == "market-tax"
    assert restored_trial.get_json()["events"][0]["event_type"] == ("experiments.scenario.apply")
    assert idempotent_launch.get_json()["report_id"] == report_id


def test_calibration_review_and_policy_promotion_are_distinct_api_actions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(artifact_root=tmp_path)
    with app.test_client() as client:
        comparison = client.post(
            "/api/v2/calibration/compare",
            json={
                "synthetic_metrics": {"completion": 0.9},
                "human_metrics": {"completion": 0.7},
                "policy_version": "policy-1",
                "evidence_version": "playtest-1",
            },
        )
        report_id = comparison.get_json()["report_id"]
        premature = client.post(
            f"/api/v2/calibration/{report_id}/promote",
            json={"promoted_by": "GM Ada"},
        )
        reviewed = client.post(
            f"/api/v2/calibration/{report_id}/review",
            json={
                "reviewer": "GM Ada",
                "decision": "APPROVED",
                "rationale": "Human evidence is sufficient.",
            },
        )
        promoted = client.post(
            f"/api/v2/calibration/{report_id}/promote",
            json={"promoted_by": "GM Ada"},
        )
    assert premature.status_code == 400
    assert reviewed.status_code == 201
    assert reviewed.get_json()["report"]["promotion_id"] is None
    assert promoted.status_code == 201
    assert promoted.get_json()["promotion"]["promoted_policy_version"].startswith(
        "policy-1+calibration."
    )
    assert promoted.get_json()["report"]["promotion_id"] is not None


def test_job_restore_marks_interrupted_local_work_retryable():
    manager = JobManager()
    identity = uuid.uuid4()
    restored = manager.restore(
        JobRecord(
            job_id=identity,
            job_type="scenario.market",
            status="RUNNING",
            progress=0.4,
            request={"scenario_id": "market"},
        )
    )
    assert restored.status == "FAILED"
    assert "stopped" in (restored.error or "")


def test_scenario_route_selects_latest_numeric_version(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    local_app = create_app(artifact_root=tmp_path)
    base = {
        "scenario_id": "version-order",
        "cohort_size": 1,
        "seeds": [7],
        "intervention": {"deltas": []},
    }
    with local_app.test_client() as client:
        assert (
            client.post("/api/v2/scenarios", json={**base, "version": "1.9.0"}).status_code == 201
        )
        assert (
            client.post("/api/v2/scenarios", json={**base, "version": "1.10.0"}).status_code == 201
        )
        launched = client.post(
            "/api/v2/scenarios/version-order/run",
            json={"cohort_size": 1, "seeds": [7], "include_trials": 1},
        )

    assert launched.status_code == 201
    assert launched.get_json()["report"]["scenario_version"] == "1.10.0"
