from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from experiments.aggregation import ReportBuilder
from experiments.artifacts import LocalArtifactStore
from experiments.models import (
    CohortReport,
    ScenarioDefinition,
    TrialOutput,
    scenario_version_key,
)
from experiments.scenario_lab import ScenarioLab

pytestmark = pytest.mark.unit


def _cohort(version: str) -> CohortReport:
    return CohortReport(
        scenario_id="market",
        scenario_version=version,
        trial_count=0,
        completed=0,
        completion_rate=0,
        canonical_world_unchanged=True,
        metrics={},
        sample_trials=(),
    )


def _trial(number: int, score: float) -> TrialOutput:
    return TrialOutput(
        trial_id=uuid.UUID(int=number),
        persona_id=uuid.UUID(int=number + 100),
        seed=number,
        status="COMPLETED",
        steps=2,
        canonical_hash_before="same",
        canonical_hash_after="same",
        trial_state_hash=f"trial-{number}",
        traces=(),
        facts=(),
        metrics={"score": score, "completed": True},
    )


def test_scenario_versions_are_crud_managed_as_immutable_tombstones(tmp_path):
    artifacts = LocalArtifactStore(tmp_path)
    lab = ScenarioLab(artifacts)
    first = ScenarioDefinition(scenario_id="market", version="1.0.0", name="Tax 10%")
    second = ScenarioDefinition(scenario_id="market", version="2.0.0", name="Tax 15%")

    record1 = lab.create(first, lambda definition: _cohort(definition.version))
    record2 = lab.update(
        "market",
        "1.0.0",
        second,
        lambda definition: _cohort(definition.version),
    )
    report_id, report = lab.run("market", "2.0.0")
    archived = lab.delete("market", "1.0.0")

    assert record1.content_hash != record2.content_hash
    assert record2.predecessor_version == "1.0.0"
    assert lab.get("market", "1.0.0").definition == first
    assert archived.status == "ARCHIVED"
    assert lab.definitions() == (second,)
    assert lab.definitions(include_archived=True) == (first, second)
    assert lab.report(report_id) == report
    assert lab.reports_for("market", "2.0.0") == ((report_id, report),)
    with pytest.raises(ValueError, match="Archived scenarios"):
        lab.run("market", "1.0.0")


def test_scenario_identity_is_canonical_and_executor_report_version_is_checked():
    left = ScenarioDefinition(
        scenario_id="canonical",
        version="1.0.0",
        world_setup={"a": 1, "b": 2},
    )
    right = ScenarioDefinition(
        scenario_id="canonical-copy",
        version="1.0.0",
        world_setup={"b": 2, "a": 1},
    )
    lab = ScenarioLab()
    left_record = lab.create(left)
    right_record = lab.create(right)

    left.world_setup["a"] = 99
    left_record.definition.world_setup["b"] = 99
    assert lab.get("canonical", "1.0.0").definition.world_setup == {"a": 1, "b": 2}

    # The scenario key differs, so compare the content suffix after normalizing that field.
    normalized = right.model_copy(update={"scenario_id": "canonical"})
    normalized_lab = ScenarioLab()
    normalized_record = normalized_lab.create(normalized)
    assert left_record.content_hash == normalized_record.content_hash
    assert left_record.content_hash != right_record.content_hash

    mismatch = ScenarioLab()
    mismatch.create(left, lambda _definition: _cohort("wrong"))
    with pytest.raises(ValueError, match="another version"):
        mismatch.run("canonical", "1.0.0")


def test_scenario_identifiers_and_versions_are_route_safe_and_numerically_ordered():
    assert scenario_version_key("1.10.0") > scenario_version_key("1.9.0")
    for invalid in (
        {"scenario_id": "", "version": "1.0.0"},
        {"scenario_id": "not/a/route", "version": "1.0.0"},
        {"scenario_id": "market", "version": ""},
        {"scenario_id": "market", "version": "1.9"},
    ):
        with pytest.raises(ValidationError):
            ScenarioDefinition.model_validate(invalid)


def test_report_and_comparison_artifacts_are_content_addressed(tmp_path):
    artifacts = LocalArtifactStore(tmp_path)
    builder = ReportBuilder(artifacts)
    baseline = builder.build(
        "opening",
        "1",
        (_trial(1, 2), _trial(2, 4)),
        cohort_slices={"novice": (_trial(1, 2),)},
    )
    candidate = builder.build("opening", "2", (_trial(3, 5), _trial(4, 7)))
    comparison = builder.compare(
        "new-opening",
        baseline,
        candidate,
        metric_contract_version="metrics-1",
    )

    assert baseline.aggregate["means"]["score"] == 3
    assert baseline.cohort_slices["novice"]["means"]["score"] == 2
    assert baseline.artifact is not None
    assert LocalArtifactStore.read(baseline.artifact)["report_id"] == str(baseline.report_id)
    assert comparison.metrics["score"]["delta"] == 3
    assert comparison.artifact is not None
