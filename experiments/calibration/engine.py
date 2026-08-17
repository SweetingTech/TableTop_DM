from __future__ import annotations

import json
import math
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from experiments.models import CalibrationPromotion, CalibrationReview


class MetricCalibration(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: str
    synthetic_value: float
    human_value: float
    absolute_error: float
    relative_error: float | None


class CalibrationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: uuid.UUID
    synthetic_policy_version: str
    evidence_version: str
    metrics: tuple[MetricCalibration, ...]
    root_mean_squared_error: float
    proposed_policy_version: str
    promotion_status: str = "REVIEW_REQUIRED"
    human_ground_truth_claimed: bool = False
    proposed_adjustments: dict[str, float] = Field(default_factory=dict)
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)
    approved_by: str | None = None
    approved_at: datetime | None = None
    review_id: uuid.UUID | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    promotion_id: uuid.UUID | None = None
    promoted_by: str | None = None
    promoted_at: datetime | None = None


class CalibrationEngine:
    VERSION = "calibration-engine-1.0.0"

    def compare(
        self,
        synthetic_metrics: dict[str, float],
        human_metrics: dict[str, float],
        policy_version: str,
        evidence_version: str,
        evidence_metadata: dict[str, Any] | None = None,
    ) -> CalibrationReport:
        shared = sorted(set(synthetic_metrics) & set(human_metrics))
        if not shared:
            raise ValueError("Synthetic and human evidence share no metrics")
        metrics: list[MetricCalibration] = []
        squared_errors = []
        for name in shared:
            synthetic = float(synthetic_metrics[name])
            human = float(human_metrics[name])
            error = abs(synthetic - human)
            squared_errors.append((synthetic - human) ** 2)
            metrics.append(
                MetricCalibration(
                    metric=name,
                    synthetic_value=synthetic,
                    human_value=human,
                    absolute_error=round(error, 6),
                    relative_error=None if human == 0 else round(error / abs(human), 6),
                )
            )
        report_key: dict[str, Any] = {
            "policy": policy_version,
            "evidence": evidence_version,
            "synthetic": synthetic_metrics,
            "human": human_metrics,
            "evidence_metadata": evidence_metadata or {},
        }
        report_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            json.dumps(report_key, sort_keys=True, separators=(",", ":")),
        )
        proposed = f"{policy_version}+calibration.{str(report_id)[:8]}"
        return CalibrationReport(
            report_id=report_id,
            synthetic_policy_version=policy_version,
            evidence_version=evidence_version,
            metrics=tuple(metrics),
            root_mean_squared_error=round(math.sqrt(sum(squared_errors) / len(shared)), 6),
            proposed_policy_version=proposed,
            proposed_adjustments={
                item.metric: round(item.human_value - item.synthetic_value, 6) for item in metrics
            },
            evidence_metadata=evidence_metadata or {},
        )


class CalibrationStore:
    """Review gate for immutable calibration proposals."""

    def __init__(self, artifact_root: Path | None = None) -> None:
        self.artifact_root = artifact_root.resolve() if artifact_root else None
        self._reports: dict[uuid.UUID, CalibrationReport] = {}
        self._reviews: dict[uuid.UUID, CalibrationReview] = {}
        self._promotions: dict[uuid.UUID, CalibrationPromotion] = {}
        self._load_artifacts()

    def _load_artifacts(self) -> None:
        if self.artifact_root is None or not self.artifact_root.exists():
            return
        for path in sorted(self.artifact_root.glob("*.json")):
            if path.name.endswith((".review.json", ".promotion.json")):
                continue
            report = CalibrationReport.model_validate_json(path.read_text(encoding="utf-8"))
            self._reports[report.report_id] = report
        for path in sorted(self.artifact_root.glob("*.review.json")):
            review = CalibrationReview.model_validate_json(path.read_text(encoding="utf-8"))
            if review.report_id not in self._reports:
                raise ValueError("calibration review has no proposal artifact")
            self._reviews[review.report_id] = review
        for path in sorted(self.artifact_root.glob("*.promotion.json")):
            promotion = CalibrationPromotion.model_validate_json(path.read_text(encoding="utf-8"))
            if promotion.report_id not in self._reports:
                raise ValueError("calibration promotion has no proposal artifact")
            self._promotions[promotion.report_id] = promotion

    def add(self, report: CalibrationReport) -> CalibrationReport:
        if (
            report.promotion_status != "REVIEW_REQUIRED"
            or report.human_ground_truth_claimed
            or report.approved_by is not None
            or report.approved_at is not None
            or report.review_id is not None
            or report.promotion_id is not None
        ):
            raise ValueError("Only unreviewed calibration proposals can be added")
        existing = self._reports.get(report.report_id)
        if existing is not None and existing != report:
            raise ValueError("An immutable calibration proposal cannot be replaced")
        proposal = (existing or report).model_copy(deep=True)
        self._write_proposal(proposal)
        self._reports.setdefault(report.report_id, proposal)
        return proposal.model_copy(deep=True)

    def list(self) -> tuple[CalibrationReport, ...]:
        return tuple(self._view(key) for key in sorted(self._reports, key=str))

    def get(self, report_id: uuid.UUID) -> CalibrationReport:
        return self._view(report_id)

    def proposal(self, report_id: uuid.UUID) -> CalibrationReport:
        """Return the immutable evidence proposal without lifecycle overlays."""
        return self._reports[report_id].model_copy(deep=True)

    def approve(self, report_id: uuid.UUID, reviewer: str) -> CalibrationReport:
        self.review(report_id, reviewer, "APPROVED")
        return self.get(report_id)

    def review(
        self,
        report_id: uuid.UUID,
        reviewer: str,
        decision: Literal["APPROVED", "REJECTED"],
        *,
        rationale: str = "",
        reviewed_at: datetime | None = None,
    ) -> CalibrationReview:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("decision must be APPROVED or REJECTED")
        if report_id not in self._reports:
            raise KeyError(report_id)
        if report_id in self._reviews:
            raise ValueError("calibration proposal has already been reviewed")
        reviewer = reviewer.strip()
        review_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:calibration-review:{report_id}:{decision}:{reviewer}:{rationale.strip()}",
        )
        review = CalibrationReview(
            review_id=review_id,
            report_id=report_id,
            decision=decision,
            reviewer=reviewer,
            rationale=rationale.strip(),
            reviewed_at=reviewed_at or datetime.now(UTC),
        )
        self._write_review(review)
        self._reviews[report_id] = review
        return review

    def promote(
        self,
        report_id: uuid.UUID,
        promoted_by: str,
        *,
        promoted_at: datetime | None = None,
    ) -> CalibrationPromotion:
        if not promoted_by.strip():
            raise ValueError("promoted_by is required")
        review = self._reviews.get(report_id)
        if review is None or review.decision != "APPROVED":
            raise ValueError("an approved review is required before promotion")
        if report_id in self._promotions:
            raise ValueError("calibration proposal has already been promoted")
        report = self._reports[report_id]
        promoted_by = promoted_by.strip()
        promotion_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:calibration-promotion:{report_id}:{review.review_id}:"
            f"{report.proposed_policy_version}:{promoted_by}",
        )
        promotion = CalibrationPromotion(
            promotion_id=promotion_id,
            report_id=report_id,
            review_id=review.review_id,
            promoted_policy_version=report.proposed_policy_version,
            promoted_by=promoted_by,
            promoted_at=promoted_at or datetime.now(UTC),
        )
        self._write_promotion(promotion)
        self._promotions[report_id] = promotion
        return promotion

    def review_for(self, report_id: uuid.UUID) -> CalibrationReview | None:
        return self._reviews.get(report_id)

    def promotion_for(self, report_id: uuid.UUID) -> CalibrationPromotion | None:
        return self._promotions.get(report_id)

    def _view(self, report_id: uuid.UUID) -> CalibrationReport:
        report = self._reports[report_id]
        review = self._reviews.get(report_id)
        promotion = self._promotions.get(report_id)
        updates: dict[str, Any] = {}
        if review is not None:
            updates.update(
                {
                    "promotion_status": review.decision,
                    "review_id": review.review_id,
                    "reviewed_by": review.reviewer,
                    "reviewed_at": review.reviewed_at,
                    "approved_by": (review.reviewer if review.decision == "APPROVED" else None),
                    "approved_at": (review.reviewed_at if review.decision == "APPROVED" else None),
                }
            )
        if promotion is not None:
            updates.update(
                {
                    "promotion_id": promotion.promotion_id,
                    "promoted_by": promotion.promoted_by,
                    "promoted_at": promotion.promoted_at,
                }
            )
        view = report.model_copy(update=updates) if updates else report
        return view.model_copy(deep=True)

    def _write_proposal(self, report: CalibrationReport) -> None:
        if self.artifact_root is None:
            return
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        destination = self.artifact_root / f"{report.report_id}.json"
        if destination.exists():
            existing = CalibrationReport.model_validate_json(
                destination.read_text(encoding="utf-8")
            )
            if existing != report:
                raise ValueError("Calibration proposal artifact is immutable")
            return
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, destination)

    def _write_review(self, review: CalibrationReview) -> None:
        if self.artifact_root is None:
            return
        destination = self.artifact_root / f"{review.report_id}.review.json"
        if destination.exists():
            existing = CalibrationReview.model_validate_json(
                destination.read_text(encoding="utf-8")
            )
            if existing != review:
                raise ValueError("Calibration review artifact is immutable")
            return
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(review.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, destination)

    def _write_promotion(self, promotion: CalibrationPromotion) -> None:
        if self.artifact_root is None:
            return
        destination = self.artifact_root / f"{promotion.report_id}.promotion.json"
        if destination.exists():
            existing = CalibrationPromotion.model_validate_json(
                destination.read_text(encoding="utf-8")
            )
            if existing != promotion:
                raise ValueError("Calibration promotion artifact is immutable")
            return
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(promotion.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, destination)
