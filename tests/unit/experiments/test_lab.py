import uuid

import pytest

from experiments.aggregation import aggregate_metrics, compare_reports
from experiments.calibration import CalibrationEngine, CalibrationStore
from experiments.jobs import JobManager
from experiments.models import TrialOutput
from experiments.telemetry import TelemetryRecorder, TelemetrySettingsStore

pytestmark = pytest.mark.unit


def trial(value: float) -> TrialOutput:
    return TrialOutput(
        trial_id=uuid.uuid4(),
        persona_id=uuid.uuid4(),
        seed=1,
        status="COMPLETED",
        steps=2,
        canonical_hash_before="a",
        canonical_hash_after="a",
        trial_state_hash="b",
        traces=(),
        facts=(),
        metrics={"completion": True, "score": value},
    )


def test_aggregation_labels_synthetic_results_and_compares_deltas():
    result = aggregate_metrics((trial(2), trial(4)))
    assert result["means"]["score"] == 3
    assert result["synthetic_results_are_hypotheses"] is True
    comparison = compare_reports({"score": 3}, {"score": 4.5})
    assert comparison["metrics"]["score"]["delta"] == 1.5


def test_job_failure_retry_and_idempotent_completed_submission():
    jobs = JobManager()
    attempts = {"count": 0}

    def flaky(_request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient")
        return {"ok": True}

    queued = jobs.create("test", {"seed": 1}, flaky)
    assert jobs.run(queued.job_id).status == "FAILED"
    assert jobs.retry(queued.job_id).attempt == 2
    finished = jobs.run(queued.job_id)
    assert finished.status == "COMPLETED"
    assert jobs.create("test", {"seed": 1}, flaky) == finished


def test_calibration_requires_human_review_before_policy_approval(tmp_path):
    report = CalibrationEngine().compare(
        {"completion": 0.9},
        {"completion": 0.7},
        "policy-1",
        "playtest-1",
        {"participants": 8, "consent": "v1"},
    )
    store = CalibrationStore(tmp_path)
    store.add(report)
    assert report.promotion_status == "REVIEW_REQUIRED"
    assert report.human_ground_truth_claimed is False
    approved = store.approve(report.report_id, "GM Ada")
    assert approved.promotion_status == "APPROVED"
    assert approved.approved_by == "GM Ada"
    assert (tmp_path / f"{report.report_id}.json").exists()


def test_telemetry_is_opt_in_redacted_and_deletable(tmp_path):
    settings = TelemetrySettingsStore()
    settings.set_enabled(False)
    recorder = TelemetryRecorder(settings)
    with pytest.raises(PermissionError):
        recorder.capture("action", {"name": "move"}, "v1")
    settings.set_enabled(True)
    event = recorder.capture("action", {"token": "secret", "name": "move"}, "v1")
    assert event.payload["token"] == "[REDACTED]"
    destination = recorder.export(tmp_path / "telemetry.jsonl")
    assert destination.exists()
    assert recorder.delete_all() == 1
