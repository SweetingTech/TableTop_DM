from __future__ import annotations

import uuid
from collections.abc import Callable
from statistics import mean

from experiments.executor import ApplicationBranchExecutor
from experiments.models import CohortReport, ScenarioDefinition, SnapshotReference, TrialOutput
from experiments.trial_engine import TrialEngine, TrialLifecycleRepository
from experiments.verifiers import VerifierRegistry
from kernel.contracts import EventEnvelopeV2, VerifierFact

PersonaFactory = Callable[[int, int], tuple[uuid.UUID, str]]
TrialProgress = Callable[[int, int, TrialOutput], None]

REFERENCE_VERIFIER = "scenario.reference@1.0.0"
REFERENCE_METRIC_CONTRACT = {
    "version": "scenario-reference-metrics-1.0.0",
    "metrics": [
        {
            "name": "completed",
            "fact_type": "scenario.completed",
            "reduction": "VALUE",
        },
        {
            "name": "intervention_applied",
            "fact_type": "scenario.intervention_applied",
            "reduction": "VALUE",
        },
        {
            "name": "steps",
            "fact_type": "scenario.steps",
            "reduction": "VALUE",
        },
        {
            "name": "verified_delta_count",
            "fact_type": "scenario.delta_count",
            "reduction": "VALUE",
        },
    ],
}


def _reference_verifier(
    events: tuple[EventEnvelopeV2, ...],
    final_state: dict,
) -> tuple[VerifierFact, ...]:
    if not events:
        raise ValueError("reference scenario verifier requires a committed event")
    event = events[-1]
    if event.event_type != "experiments.scenario.apply":
        raise ValueError("reference scenario verifier received an unrelated event")
    records = final_state.get("experiments.scenario_runs", {})
    matching = [
        value
        for value in records.values()
        if value.get("scenario_id") == event.payload.get("scenario_id")
        and value.get("scenario_version") == event.payload.get("scenario_version")
    ]
    if len(matching) != 1:
        raise ValueError("trial state does not contain exactly one matching scenario record")
    record = matching[0]
    evidence = (event.event_id,)
    return (
        VerifierFact(
            fact_type="scenario.completed",
            value=record.get("status") == "COMPLETED",
            evidence_event_ids=evidence,
            verifier_version="scenario-reference-verifier-1.0.0",
        ),
        VerifierFact(
            fact_type="scenario.intervention_applied",
            value=bool(record.get("intervention_applied")),
            evidence_event_ids=evidence,
            verifier_version="scenario-reference-verifier-1.0.0",
        ),
        VerifierFact(
            fact_type="scenario.steps",
            value=1,
            unit="steps",
            evidence_event_ids=evidence,
            verifier_version="scenario-reference-verifier-1.0.0",
        ),
        VerifierFact(
            fact_type="scenario.delta_count",
            value=int(event.payload.get("delta_count", 0)),
            unit="deltas",
            evidence_event_ids=evidence,
            verifier_version="scenario-reference-verifier-1.0.0",
        ),
    )


class ReferenceScenarioRunner:
    """Cohort runner for immutable, generic ScenarioDefinition contracts."""

    def __init__(
        self,
        executor: ApplicationBranchExecutor,
        *,
        repository: TrialLifecycleRepository | None = None,
        persona_factory: PersonaFactory | None = None,
    ) -> None:
        verifiers = VerifierRegistry()
        verifiers.register("scenario.reference", _reference_verifier, version="1.0.0")
        self.executor = executor
        self.engine = TrialEngine(verifiers, repository=repository)
        self.persona_factory = persona_factory
        self.last_outputs: tuple[TrialOutput, ...] = ()

    def run(
        self,
        definition: ScenarioDefinition,
        snapshot: SnapshotReference,
        *,
        cohort_size: int | None = None,
        seeds: tuple[int, ...] | None = None,
        include_trials: int = 12,
        attempt: int = 1,
        cancelled: Callable[[], bool] | None = None,
        on_trial: TrialProgress | None = None,
    ) -> CohortReport:
        size = definition.cohort_size if cohort_size is None else cohort_size
        selected_seeds = definition.seeds if seeds is None else seeds
        if size < 1 or size > 10_000:
            raise ValueError("cohort_size must be between 1 and 10000")
        if not selected_seeds:
            raise ValueError("At least one seed is required")
        if include_trials < 0:
            raise ValueError("include_trials cannot be negative")
        effective = definition.model_copy(
            update={
                "base_snapshot_id": snapshot.snapshot_id,
                "verifier_versions": definition.verifier_versions or (REFERENCE_VERIFIER,),
                "metric_contract": definition.metric_contract or REFERENCE_METRIC_CONTRACT,
            }
        )
        total = size * len(selected_seeds)
        outputs: list[TrialOutput] = []
        is_cancelled = cancelled or (lambda: False)
        for seed in selected_seeds:
            for index in range(size):
                if is_cancelled():
                    break
                persona_id: uuid.UUID | None = None
                persona_version: str | None = None
                if self.persona_factory is not None:
                    persona_id, persona_version = self.persona_factory(
                        seed * 100_000 + index,
                        index,
                    )
                    self.executor.bind_persona_version(persona_id, persona_version)
                output = self.engine.run(
                    effective,
                    snapshot,
                    self.executor,
                    persona_id=persona_id,
                    persona_version=persona_version,
                    seed=seed,
                    attempt=attempt,
                    cancelled=is_cancelled,
                )
                outputs.append(output)
                if on_trial is not None:
                    on_trial(len(outputs), total, output)
            if is_cancelled():
                break

        completed = sum(output.status == "COMPLETED" for output in outputs)
        metric_names = sorted(
            {
                name
                for output in outputs
                for name, value in output.metrics.items()
                if isinstance(value, (bool, int, float))
            }
        )
        metrics = {
            name: round(
                mean(
                    float(output.metrics[name])
                    for output in outputs
                    if isinstance(output.metrics.get(name), (bool, int, float))
                ),
                6,
            )
            for name in metric_names
        }
        self.last_outputs = tuple(outputs)
        return CohortReport(
            scenario_id=definition.scenario_id,
            scenario_version=definition.version,
            trial_count=len(outputs),
            completed=completed,
            completion_rate=round(completed / len(outputs), 6) if outputs else 0.0,
            canonical_world_unchanged=all(
                output.canonical_hash_before == output.canonical_hash_after for output in outputs
            ),
            metrics=metrics,
            sample_trials=tuple(outputs[:include_trials]),
        )
