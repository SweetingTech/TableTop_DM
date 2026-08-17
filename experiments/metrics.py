from __future__ import annotations

from statistics import mean
from typing import Any

from experiments.models import MetricContract, MetricSpec
from kernel.contracts import VerifierFact


class MetricEvaluator:
    VERSION = "metric-evaluator-1.0.0"

    def evaluate(
        self,
        facts: tuple[VerifierFact, ...],
        contract: MetricContract,
    ) -> dict[str, Any]:
        names = [spec.name for spec in contract.metrics]
        if len(names) != len(set(names)):
            raise ValueError("Metric contract names must be unique")
        return {
            spec.name: self._reduce(
                spec,
                tuple(fact.value for fact in facts if fact.fact_type == spec.fact_type),
            )
            for spec in contract.metrics
        }

    @staticmethod
    def _reduce(spec: MetricSpec, values: tuple[Any, ...]) -> Any:
        if not values:
            if spec.default is None:
                raise ValueError(f"Metric {spec.name} has no {spec.fact_type} facts and no default")
            return spec.default
        if spec.reduction == "VALUE":
            if len(values) != 1:
                raise ValueError(f"Metric {spec.name} expected one fact, found {len(values)}")
            return values[0]
        if spec.reduction == "COUNT":
            return len(values)
        if spec.reduction == "ANY":
            return any(bool(value) for value in values)
        if spec.reduction == "ALL":
            return all(bool(value) for value in values)
        numeric = [float(value) for value in values]
        if spec.reduction == "SUM":
            return round(sum(numeric), 6)
        if spec.reduction == "MEAN":
            return round(mean(numeric), 6)
        raise ValueError(f"Unknown metric reduction {spec.reduction}")
