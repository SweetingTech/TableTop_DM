from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Protocol

from experiments.executor import BranchExecutor
from experiments.metrics import MetricEvaluator
from experiments.models import (
    MetricContract,
    ScenarioDefinition,
    SnapshotReference,
    TrialOutput,
    TrialRecord,
)
from experiments.verifiers import VerifierRegistry


class TrialLifecycleRepository(Protocol):
    def save_trial(self, record: TrialRecord) -> None: ...

    def save_output(self, record: TrialRecord, output: TrialOutput) -> None: ...


class TrialIsolationError(RuntimeError):
    pass


class TrialEngine:
    VERSION = "trial-engine-1.0.0"

    def __init__(
        self,
        verifiers: VerifierRegistry,
        *,
        metrics: MetricEvaluator | None = None,
        repository: TrialLifecycleRepository | None = None,
    ) -> None:
        self.verifiers = verifiers
        self.metrics = metrics or MetricEvaluator()
        self.repository = repository

    def run(
        self,
        scenario: ScenarioDefinition,
        snapshot: SnapshotReference,
        executor: BranchExecutor,
        *,
        persona_id: uuid.UUID | None,
        persona_version: str | None,
        seed: int,
        attempt: int = 1,
        checkpoint: dict[str, Any] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> TrialOutput:
        if (
            scenario.base_snapshot_id is not None
            and scenario.base_snapshot_id != snapshot.snapshot_id
        ):
            raise ValueError("Scenario base snapshot does not match executor snapshot")
        if (persona_id is None) != (persona_version is None):
            raise ValueError("persona_id and persona_version must be supplied together")
        if attempt < 1:
            raise ValueError("attempt must be positive")
        checkpoint = checkpoint or {}
        cancelled = cancelled or (lambda: False)
        trial_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:generic-trial:{scenario.scenario_id}:{scenario.version}:"
            f"{snapshot.snapshot_id}:{persona_id}:{seed}:{attempt}",
        )
        canonical_before = executor.canonical_hash(snapshot)
        branch = executor.create_trial_branch(snapshot, trial_id, seed)
        running = TrialRecord(
            trial_id=trial_id,
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.version,
            persona_id=persona_id,
            persona_version=persona_version,
            world_id=snapshot.world_id,
            snapshot_id=snapshot.snapshot_id,
            branch_id=branch.branch_id,
            run_id=branch.run_id,
            seed=seed,
            status="RUNNING",
            attempt=attempt,
            checkpoint=checkpoint,
        )
        if self.repository is not None:
            self.repository.save_trial(running)

        try:
            execution = executor.execute(
                scenario,
                branch,
                persona_id,
                seed,
                checkpoint,
                cancelled,
            )
            canonical_after = executor.canonical_hash(snapshot)
            if canonical_after != canonical_before:
                raise TrialIsolationError(
                    "Trial executor changed the canonical snapshot state hash"
                )
            facts = self.verifiers.verify(
                scenario.verifier_versions,
                execution.events,
                execution.final_state,
            )
            contract = MetricContract.model_validate(scenario.metric_contract or {})
            evaluated = self.metrics.evaluate(facts, contract)
            output = TrialOutput(
                trial_id=trial_id,
                persona_id=persona_id,
                seed=seed,
                status=execution.status,
                steps=execution.steps,
                canonical_hash_before=canonical_before,
                canonical_hash_after=canonical_after,
                trial_state_hash=execution.trial_state_hash,
                traces=execution.traces,
                events=execution.events,
                facts=facts,
                metrics={**execution.metrics, **evaluated},
                branch_id=branch.branch_id,
                run_id=branch.run_id,
                artifact_uris=execution.artifact_uris,
                failure_code=execution.failure_code,
            )
            terminal_status = (
                "CANCELLED"
                if execution.status == "CANCELLED"
                else "FAILED"
                if execution.status == "FAILED"
                else "COMPLETED"
            )
            completed = running.model_copy(
                update={
                    "status": terminal_status,
                    "checkpoint": execution.checkpoint,
                    "failure_code": execution.failure_code,
                }
            )
            if self.repository is not None:
                self.repository.save_output(completed, output)
            return output
        except Exception as exc:
            isolation_failure: TrialIsolationError | None = None
            try:
                canonical_after_failure = executor.canonical_hash(snapshot)
            except Exception as hash_error:
                isolation_failure = TrialIsolationError(
                    "Canonical state could not be verified after trial failure"
                )
                isolation_failure.add_note(
                    f"canonical hash check failed with {type(hash_error).__name__}"
                )
            else:
                if canonical_after_failure != canonical_before:
                    isolation_failure = TrialIsolationError(
                        "Trial executor changed canonical state while failing"
                    )
            if self.repository is not None:
                self.repository.save_trial(
                    running.model_copy(
                        update={
                            "status": "FAILED",
                            "failure_code": type(isolation_failure or exc).__name__,
                        }
                    )
                )
            if isolation_failure is not None:
                raise isolation_failure from exc
            raise
