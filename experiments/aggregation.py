from __future__ import annotations

import json
import uuid
from collections import defaultdict
from statistics import mean
from typing import Any

from experiments.artifacts import LocalArtifactStore
from experiments.models import ComparisonReport, ExperimentReport, TrialOutput


def aggregate_metrics(
    trials: tuple[TrialOutput, ...], cohort_dimensions: dict[str, str] | None = None
) -> dict[str, Any]:
    numeric: dict[str, list[float]] = defaultdict(list)
    status: dict[str, int] = defaultdict(int)
    for trial in trials:
        status[trial.status] += 1
        for name, value in trial.metrics.items():
            if isinstance(value, bool):
                numeric[name].append(float(value))
            elif isinstance(value, (int, float)):
                numeric[name].append(float(value))
    return {
        "trial_count": len(trials),
        "statuses": dict(sorted(status.items())),
        "means": {name: round(mean(values), 6) for name, values in sorted(numeric.items())},
        "cohort_dimensions": cohort_dimensions or {},
        "synthetic_results_are_hypotheses": True,
    }


def compare_reports(left: dict[str, float], right: dict[str, float]) -> dict[str, Any]:
    shared = sorted(set(left) & set(right))
    return {
        "metrics": {
            name: {
                "left": float(left[name]),
                "right": float(right[name]),
                "delta": round(float(right[name]) - float(left[name]), 6),
            }
            for name in shared
        },
        "synthetic_results_are_hypotheses": True,
    }


class ReportBuilder:
    def __init__(self, artifacts: LocalArtifactStore | None = None) -> None:
        self.artifacts = artifacts

    def build(
        self,
        scenario_id: str,
        scenario_version: str,
        trials: tuple[TrialOutput, ...],
        *,
        cohort_slices: dict[str, tuple[TrialOutput, ...]] | None = None,
    ) -> ExperimentReport:
        aggregate = aggregate_metrics(trials)
        slices = {
            name: aggregate_metrics(slice_trials)
            for name, slice_trials in sorted((cohort_slices or {}).items())
        }
        identity = json.dumps(
            {
                "scenario": scenario_id,
                "version": scenario_version,
                "trials": sorted(str(trial.trial_id) for trial in trials),
                "aggregate": aggregate,
                "slices": slices,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        report_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:experiment-report:{identity}",
        )
        report = ExperimentReport(
            report_id=report_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            trial_ids=tuple(sorted((trial.trial_id for trial in trials), key=str)),
            aggregate=aggregate,
            cohort_slices=slices,
        )
        if self.artifacts is None:
            return report
        artifact = self.artifacts.write_json(
            "experiment-report",
            str(report_id),
            report.model_dump(mode="json"),
        )
        return report.model_copy(update={"artifact": artifact})

    def compare(
        self,
        name: str,
        baseline: ExperimentReport,
        candidate: ExperimentReport,
        *,
        metric_contract_version: str,
    ) -> ComparisonReport:
        baseline_means = baseline.aggregate.get("means", {})
        candidate_means = candidate.aggregate.get("means", {})
        comparison = compare_reports(baseline_means, candidate_means)
        identity = json.dumps(
            {
                "name": name,
                "baseline": str(baseline.report_id),
                "candidate": str(candidate.report_id),
                "contract": metric_contract_version,
                "metrics": comparison["metrics"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        comparison_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:experiment-comparison:{identity}",
        )
        report = ComparisonReport(
            comparison_id=comparison_id,
            name=name,
            baseline_report_id=baseline.report_id,
            candidate_report_id=candidate.report_id,
            metric_contract_version=metric_contract_version,
            metrics=comparison["metrics"],
        )
        if self.artifacts is None:
            return report
        artifact = self.artifacts.write_json(
            "experiment-comparison",
            str(comparison_id),
            report.model_dump(mode="json"),
        )
        return report.model_copy(update={"artifact": artifact})
