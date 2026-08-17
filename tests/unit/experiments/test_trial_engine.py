from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from experiments.executor import InMemoryBranchExecutor
from experiments.models import (
    ScenarioDefinition,
    SnapshotReference,
    TrialExecution,
)
from experiments.repository import InMemoryExperimentRepository
from experiments.trial_engine import TrialEngine, TrialIsolationError
from experiments.verifiers import VerifierRegistry
from kernel.contracts import EventEnvelopeV2, VerifierFact

pytestmark = pytest.mark.unit


def _snapshot() -> SnapshotReference:
    return SnapshotReference(
        snapshot_id=uuid.UUID(int=1000),
        world_id=uuid.UUID(int=1001),
        canonical_branch_id=uuid.UUID(int=1002),
        state_hash="canonical-hash",
    )


def _scenario(snapshot: SnapshotReference) -> ScenarioDefinition:
    return ScenarioDefinition(
        scenario_id="generic-test",
        version="1.0.0",
        base_snapshot_id=snapshot.snapshot_id,
        verifier_versions=("score@1.0.0",),
        metric_contract={
            "version": "score-contract-1",
            "metrics": [
                {
                    "name": "verified_score",
                    "fact_type": "trial.score",
                    "reduction": "VALUE",
                }
            ],
        },
    )


def test_generic_trial_is_reproducible_verified_and_branch_isolated():
    snapshot = _snapshot()

    def handler(scenario, branch, state, persona_id, seed, checkpoint, cancelled):
        state["score"] = 7
        event = EventEnvelopeV2(
            event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"score:{branch.branch_id}"),
            world_id=branch.world_id,
            branch_id=branch.branch_id,
            run_id=branch.run_id,
            actor_id=uuid.UUID(int=1003),
            event_type="trial.scored",
            payload={"score": 7},
            visible_to=(uuid.UUID(int=1003),),
            correlation_id=branch.trial_id,
            created_at=datetime(2040, 1, 1, tzinfo=UTC),
        )
        return TrialExecution(
            status="COMPLETED",
            steps=1,
            final_state=state,
            trial_state_hash="trial-hash",
            events=(event,),
            metrics={"raw_score": 6},
            checkpoint={"step": 1},
        )

    executor = InMemoryBranchExecutor(handler)
    executor.register_snapshot(snapshot, {"score": 0})
    verifiers = VerifierRegistry()
    verifiers.register(
        "score",
        lambda events, state: (
            VerifierFact(
                fact_type="trial.score",
                value=int(state["score"]),
                evidence_event_ids=(events[0].event_id,),
                verifier_version="score-1.0.0",
            ),
        ),
    )
    repository = InMemoryExperimentRepository()
    repository.save_scenario(_scenario(snapshot))
    engine = TrialEngine(verifiers, repository=repository)
    persona_id = uuid.UUID(int=1004)

    first = engine.run(
        _scenario(snapshot),
        snapshot,
        executor,
        persona_id=persona_id,
        persona_version="2.0.0",
        seed=77,
    )
    repeated = engine.run(
        _scenario(snapshot),
        snapshot,
        executor,
        persona_id=persona_id,
        persona_version="2.0.0",
        seed=77,
    )

    assert first == repeated
    assert first.canonical_hash_before == first.canonical_hash_after
    assert first.metrics == {"raw_score": 6, "verified_score": 7}
    assert first.events[0].event_type == "trial.scored"
    assert first.branch_id is not None and first.run_id is not None
    assert repository.output(first.trial_id) == first
    assert repository.trial(first.trial_id).status == "COMPLETED"


class _MutatingHashExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def canonical_hash(self, snapshot):
        self.calls += 1
        return "before" if self.calls == 1 else "after"

    def create_trial_branch(self, snapshot, trial_id, seed):
        from experiments.models import TrialBranchReference

        return TrialBranchReference(
            trial_id=trial_id,
            world_id=snapshot.world_id,
            snapshot_id=snapshot.snapshot_id,
            branch_id=uuid.UUID(int=1010),
            run_id=uuid.UUID(int=1011),
            seed=seed,
        )

    def execute(self, scenario, branch, persona_id, seed, checkpoint, cancelled):
        return TrialExecution(
            status="COMPLETED",
            steps=0,
            trial_state_hash="trial",
        )


class _FailingMutatingHashExecutor(_MutatingHashExecutor):
    def execute(self, scenario, branch, persona_id, seed, checkpoint, cancelled):
        raise RuntimeError("executor crashed after mutation")


def test_trial_engine_fails_closed_when_canonical_hash_changes():
    repository = InMemoryExperimentRepository()
    engine = TrialEngine(VerifierRegistry(), repository=repository)
    snapshot = _snapshot()

    with pytest.raises(TrialIsolationError):
        engine.run(
            ScenarioDefinition(scenario_id="bad", version="1.0.0"),
            snapshot,
            _MutatingHashExecutor(),
            persona_id=None,
            persona_version=None,
            seed=1,
        )

    assert repository.trials()[0].status == "FAILED"
    assert repository.trials()[0].failure_code == "TrialIsolationError"


def test_trial_engine_checks_canonical_hash_even_when_executor_raises():
    repository = InMemoryExperimentRepository()
    engine = TrialEngine(VerifierRegistry(), repository=repository)

    with pytest.raises(TrialIsolationError, match="while failing") as raised:
        engine.run(
            ScenarioDefinition(scenario_id="bad-failure", version="1.0.0"),
            _snapshot(),
            _FailingMutatingHashExecutor(),
            persona_id=None,
            persona_version=None,
            seed=2,
        )

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert repository.trials()[0].failure_code == "TrialIsolationError"


def test_snapshot_registration_is_immutable():
    executor = InMemoryBranchExecutor(
        lambda *_args: TrialExecution(status="COMPLETED", steps=0, trial_state_hash="trial")
    )
    snapshot = _snapshot()
    executor.register_snapshot(snapshot, {"a": 1})
    executor.register_snapshot(snapshot, {"a": 1})
    with pytest.raises(ValueError, match="cannot be replaced"):
        executor.register_snapshot(snapshot, {"a": 2})
