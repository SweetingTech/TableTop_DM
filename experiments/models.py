from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kernel.contracts import DecisionTrace, EventEnvelopeV2, VerifierFact


class ScenarioDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    version: str = Field(
        min_length=5,
        max_length=40,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$",
    )
    name: str | None = None
    description: str = ""
    base_snapshot_id: uuid.UUID | None = None
    world_setup: dict[str, Any] = Field(default_factory=dict)
    cohort: dict[str, Any] = Field(default_factory=dict)
    intervention: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    cohort_size: int = Field(default=12, gt=0, le=10_000)
    seeds: tuple[int, ...] = Field(default=(101, 202, 303), min_length=1)
    run_horizon_steps: int = Field(default=100, gt=0, le=10_000)
    stop_conditions: tuple[str, ...] = ()
    model_assignment: dict[str, Any] = Field(default_factory=dict)
    verifier_versions: tuple[str, ...] = ()
    metric_contract: dict[str, Any] = Field(default_factory=dict)


def scenario_version_key(version: str) -> tuple[int, int, int]:
    """Return the numeric ordering for a validated scenario version."""

    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


class ScenarioRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    definition: ScenarioDefinition
    content_hash: str
    status: Literal["ACTIVE", "ARCHIVED"] = "ACTIVE"
    predecessor_version: str | None = None


class SnapshotReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID
    world_id: uuid.UUID
    canonical_branch_id: uuid.UUID
    state_hash: str = Field(min_length=1)
    contract_version: str = "2.0.0"


class TrialBranchReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: uuid.UUID
    world_id: uuid.UUID
    snapshot_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    seed: int


class TrialExecution(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["COMPLETED", "HORIZON_REACHED", "FAILED", "CANCELLED"]
    steps: int = Field(ge=0)
    final_state: dict[str, Any] = Field(default_factory=dict)
    trial_state_hash: str
    events: tuple[EventEnvelopeV2, ...] = ()
    traces: tuple[DecisionTrace, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    artifact_uris: tuple[str, ...] = ()
    failure_code: str | None = None


class MetricSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    fact_type: str
    reduction: Literal["VALUE", "COUNT", "SUM", "MEAN", "ANY", "ALL"] = "VALUE"
    default: bool | int | float | str | None = None
    version: str = "1.0.0"


class MetricContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "1.0.0"
    metrics: tuple[MetricSpec, ...] = ()


class TrialOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: uuid.UUID
    persona_id: uuid.UUID | None
    seed: int
    status: str
    steps: int
    canonical_hash_before: str
    canonical_hash_after: str
    trial_state_hash: str
    traces: tuple[DecisionTrace, ...]
    events: tuple[EventEnvelopeV2, ...] = ()
    facts: tuple[VerifierFact, ...]
    metrics: dict[str, Any]
    branch_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    artifact_uris: tuple[str, ...] = ()
    failure_code: str | None = None


class TrialRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: uuid.UUID
    scenario_id: str
    scenario_version: str
    persona_id: uuid.UUID | None = None
    persona_version: str | None = None
    world_id: uuid.UUID
    snapshot_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    seed: int
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    attempt: int = Field(default=1, ge=1)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    failure_code: str | None = None


class CohortReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    scenario_version: str
    trial_count: int
    completed: int
    completion_rate: float
    canonical_world_unchanged: bool
    metrics: dict[str, float]
    sample_trials: tuple[TrialOutput, ...]


class JobRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: uuid.UUID
    job_type: str
    status: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    progress: float = Field(ge=0, le=1)
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    attempt: int = Field(default=1, ge=1)
    max_attempts: int = Field(default=3, ge=1)
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    cancellation_requested: bool = False


class ArtifactReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: uuid.UUID
    kind: str
    uri: str
    content_hash: str
    media_type: str = "application/json"


class ExperimentReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: uuid.UUID
    scenario_id: str
    scenario_version: str
    trial_ids: tuple[uuid.UUID, ...]
    aggregate: dict[str, Any]
    cohort_slices: dict[str, dict[str, Any]] = Field(default_factory=dict)
    artifact: ArtifactReference | None = None
    synthetic_results_are_hypotheses: bool = True


class ComparisonReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    comparison_id: uuid.UUID
    name: str
    baseline_report_id: uuid.UUID
    candidate_report_id: uuid.UUID
    metric_contract_version: str
    metrics: dict[str, dict[str, float]]
    artifact: ArtifactReference | None = None
    synthetic_results_are_hypotheses: bool = True


class CalibrationReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: uuid.UUID
    report_id: uuid.UUID
    decision: Literal["APPROVED", "REJECTED"]
    reviewer: str
    rationale: str = ""
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CalibrationPromotion(BaseModel):
    model_config = ConfigDict(frozen=True)

    promotion_id: uuid.UUID
    report_id: uuid.UUID
    review_id: uuid.UUID
    promoted_policy_version: str
    promoted_by: str
    promoted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
