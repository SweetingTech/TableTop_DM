from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from experiments.calibration import CalibrationEngine, CalibrationStore
from experiments.telemetry import TelemetryRecorder, TelemetrySettingsStore

pytestmark = pytest.mark.unit


def test_calibration_proposal_review_and_promotion_are_separate_immutable_artifacts(
    tmp_path,
):
    report = CalibrationEngine().compare(
        {"completion": 0.9},
        {"completion": 0.7},
        "policy-1",
        "human-playtest-1",
        {"participants": 10, "consent": "v2"},
    )
    store = CalibrationStore(tmp_path)
    store.add(report)
    report.evidence_metadata["participants"] = 999
    assert store.proposal(report.report_id).evidence_metadata["participants"] == 10
    proposal_path = tmp_path / f"{report.report_id}.json"
    original = proposal_path.read_text(encoding="utf-8")
    reviewed_at = datetime(2040, 1, 1, tzinfo=UTC)
    review = store.review(
        report.report_id,
        "GM Ada",
        "APPROVED",
        rationale="Human evidence is sufficient.",
        reviewed_at=reviewed_at,
    )
    promotion = store.promote(
        report.report_id,
        "GM Ada",
        promoted_at=reviewed_at + timedelta(minutes=1),
    )

    lifecycle = store.get(report.report_id)
    assert lifecycle.promotion_status == "APPROVED"
    assert lifecycle.review_id == review.review_id
    assert lifecycle.promotion_id == promotion.promotion_id
    assert lifecycle.promoted_by == "GM Ada"
    assert store.proposal(report.report_id).promotion_status == "REVIEW_REQUIRED"
    assert store.list() == (lifecycle,)
    assert proposal_path.read_text(encoding="utf-8") == original
    assert review.decision == "APPROVED"
    assert promotion.review_id == review.review_id
    assert promotion.promoted_policy_version == report.proposed_policy_version
    assert (tmp_path / f"{report.report_id}.review.json").exists()
    assert (tmp_path / f"{report.report_id}.promotion.json").exists()
    restored = CalibrationStore(tmp_path)
    assert restored.proposal(report.report_id) == store.proposal(report.report_id)
    assert restored.get(report.report_id) == lifecycle
    assert restored.review_for(report.report_id) == review
    assert restored.promotion_for(report.report_id) == promotion
    with pytest.raises(ValueError, match="already been reviewed"):
        store.review(report.report_id, "GM B", "REJECTED")


def test_rejected_calibration_cannot_be_promoted():
    report = CalibrationEngine().compare({"x": 1}, {"x": 2}, "p", "e")
    store = CalibrationStore()
    store.add(report)
    review = store.review(report.report_id, "Reviewer", "REJECTED")
    lifecycle = store.get(report.report_id)
    assert lifecycle.promotion_status == "REJECTED"
    assert lifecycle.review_id == review.review_id
    assert lifecycle.approved_by is None
    with pytest.raises(ValueError, match="approved review"):
        store.promote(report.report_id, "Reviewer")


def test_calibration_store_rejects_preapproved_or_ground_truth_proposals():
    report = CalibrationEngine().compare({"x": 1}, {"x": 2}, "p", "e")
    store = CalibrationStore()
    with pytest.raises(ValueError, match="unreviewed"):
        store.add(report.model_copy(update={"promotion_status": "APPROVED"}))
    with pytest.raises(ValueError, match="unreviewed"):
        store.add(report.model_copy(update={"human_ground_truth_claimed": True}))


def test_telemetry_requires_opt_in_recursively_redacts_and_selectively_deletes(tmp_path):
    settings = TelemetrySettingsStore()
    now = datetime(2041, 1, 3, tzinfo=UTC)
    moments = iter((now - timedelta(days=2), now, now))
    recorder = TelemetryRecorder(settings, clock=lambda: next(moments))
    payload = {
        "name": "move",
        "auth": {"token": "secret", "nested": [{"password": "guess"}]},
    }
    with pytest.raises(PermissionError):
        recorder.capture("action", payload, "consent-v2")
    settings.configure(enabled=True, retention_days=1)
    world_a, world_b = uuid.UUID(int=3001), uuid.UUID(int=3002)
    actor = uuid.UUID(int=3003)
    old = recorder.capture("action", payload, "consent-v2", world_id=world_a)
    current = recorder.capture("action", payload, "consent-v2", world_id=world_b, actor_id=actor)

    assert payload["auth"]["token"] == "secret"
    assert old.payload["auth"]["token"] == "[REDACTED]"
    assert old.payload["auth"]["nested"][0]["password"] == "[REDACTED]"
    current.payload["auth"]["token"] = "caller mutation"
    destination = recorder.export(tmp_path / "world-b.jsonl", world_id=world_b)
    rows = [json.loads(line) for line in destination.read_text().splitlines()]
    assert [row["event_id"] for row in rows] == [str(current.event_id)]
    assert rows[0]["payload"]["auth"]["token"] == "[REDACTED]"
    assert recorder.purge_expired(now=now) == 1
    assert recorder.delete(actor_id=actor) == 1
    assert recorder.events() == ()
    with pytest.raises(ValueError):
        settings.configure(retention_days=0)


def test_telemetry_event_identity_stays_unique_with_a_fixed_clock():
    settings = TelemetrySettingsStore()
    settings.set_enabled(True)
    captured_at = datetime(2042, 1, 1, tzinfo=UTC)
    recorder = TelemetryRecorder(settings, clock=lambda: captured_at)

    first = recorder.capture(" action ", {"name": "move"}, " consent-v3 ")
    second = recorder.capture("action", {"name": "move"}, "consent-v3")

    assert first.event_id != second.event_id
    assert first.event_type == "action"
    assert first.consent_version == "consent-v3"
    assert len(recorder.events()) == 2
