from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from experiments.models import (
    ScenarioDefinition,
    SnapshotReference,
    TrialBranchReference,
    TrialExecution,
)
from kernel.application import RunRecord, SimulationApplication
from kernel.command_bus import CommandDefinition
from kernel.contracts import (
    BranchKind,
    CommandProposal,
    CommandResult,
    RunKind,
    StateDelta,
)
from kernel.errors import BranchIsolationError
from kernel.state import BranchState


class BranchExecutor(Protocol):
    def canonical_hash(self, snapshot: SnapshotReference) -> str: ...

    def create_trial_branch(
        self,
        snapshot: SnapshotReference,
        trial_id: uuid.UUID,
        seed: int,
    ) -> TrialBranchReference: ...

    def execute(
        self,
        scenario: ScenarioDefinition,
        branch: TrialBranchReference,
        persona_id: uuid.UUID | None,
        seed: int,
        checkpoint: dict[str, Any],
        cancelled: Callable[[], bool],
    ) -> TrialExecution: ...


TrialHandler = Callable[
    [
        ScenarioDefinition,
        TrialBranchReference,
        dict[str, Any],
        uuid.UUID | None,
        int,
        dict[str, Any],
        Callable[[], bool],
    ],
    TrialExecution,
]


class InMemoryBranchExecutor:
    """Snapshot-copying reference executor used by local runs and deterministic tests."""

    def __init__(self, handler: TrialHandler) -> None:
        self.handler = handler
        self._snapshots: dict[uuid.UUID, tuple[SnapshotReference, dict[str, Any]]] = {}
        self._branches: dict[uuid.UUID, dict[str, Any]] = {}

    def register_snapshot(self, snapshot: SnapshotReference, state: dict[str, Any]) -> None:
        existing = self._snapshots.get(snapshot.snapshot_id)
        frozen_state = copy.deepcopy(state)
        if existing is not None and existing != (snapshot, frozen_state):
            raise ValueError("An immutable snapshot cannot be replaced")
        self._snapshots[snapshot.snapshot_id] = (snapshot, frozen_state)

    def canonical_hash(self, snapshot: SnapshotReference) -> str:
        registered, _ = self._snapshots[snapshot.snapshot_id]
        if registered != snapshot:
            raise ValueError("Snapshot reference does not match registered snapshot")
        return registered.state_hash

    def create_trial_branch(
        self,
        snapshot: SnapshotReference,
        trial_id: uuid.UUID,
        seed: int,
    ) -> TrialBranchReference:
        registered, state = self._snapshots[snapshot.snapshot_id]
        if registered != snapshot:
            raise ValueError("Snapshot reference does not match registered snapshot")
        branch_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:trial-branch:{snapshot.snapshot_id}:{trial_id}:{seed}",
        )
        run_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:trial-run:{snapshot.snapshot_id}:{trial_id}:{seed}",
        )
        self._branches[branch_id] = copy.deepcopy(state)
        return TrialBranchReference(
            trial_id=trial_id,
            world_id=snapshot.world_id,
            snapshot_id=snapshot.snapshot_id,
            branch_id=branch_id,
            run_id=run_id,
            seed=seed,
        )

    def execute(
        self,
        scenario: ScenarioDefinition,
        branch: TrialBranchReference,
        persona_id: uuid.UUID | None,
        seed: int,
        checkpoint: dict[str, Any],
        cancelled: Callable[[], bool],
    ) -> TrialExecution:
        if branch.branch_id not in self._branches:
            raise KeyError(f"Unknown trial branch {branch.branch_id}")
        return self.handler(
            scenario,
            branch,
            copy.deepcopy(self._branches[branch.branch_id]),
            persona_id,
            seed,
            copy.deepcopy(checkpoint),
            cancelled,
        )


class ScenarioIntervention(BaseModel):
    """Typed parameters for the domain-neutral reference scenario command."""

    model_config = ConfigDict(frozen=True)

    scenario_id: str = Field(min_length=1)
    scenario_version: str = Field(min_length=1)
    world_setup: dict[str, Any] = Field(default_factory=dict)
    intervention: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ()
    horizon_steps: int = Field(gt=0)
    deltas: tuple[StateDelta, ...] = ()


class ScenarioInterventionResult(BaseModel):
    scenario_id: str
    scenario_version: str
    intervention_applied: bool
    delta_count: int = Field(ge=0)
    status: Literal["COMPLETED"]


def _apply_scenario_intervention(
    proposal: CommandProposal,
    _state: BranchState,
) -> CommandResult:
    request = ScenarioIntervention.model_validate(proposal.parameters)
    scenario_key = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"tabletop-dm:scenario-state:{request.scenario_id}:{request.scenario_version}",
    )
    audit_delta = StateDelta(
        projection="experiments.scenario_runs",
        operation="SET",
        entity_id=scenario_key,
        values={
            "scenario_id": request.scenario_id,
            "scenario_version": request.scenario_version,
            "world_setup": request.world_setup,
            "intervention": request.intervention,
            "allowed_actions": list(request.allowed_actions),
            "stop_conditions": list(request.stop_conditions),
            "horizon_steps": request.horizon_steps,
            "status": "COMPLETED",
            "intervention_applied": bool(request.intervention),
        },
    )
    return CommandResult(
        result={
            "scenario_id": request.scenario_id,
            "scenario_version": request.scenario_version,
            "intervention_applied": bool(request.intervention),
            "delta_count": len(request.deltas),
            "status": "COMPLETED",
        },
        deltas=(*request.deltas, audit_delta),
        domain_tags=("experiments", "scenario", "intervention"),
    )


def scenario_intervention_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="experiments.scenario.apply",
        required_capabilities=frozenset({"action.propose"}),
        allowed_branch_kinds=frozenset({BranchKind.TRIAL}),
        handler=_apply_scenario_intervention,
        request_model=ScenarioIntervention,
        result_model=ScenarioInterventionResult,
        version="1.0.0",
    )


class ApplicationBranchExecutor:
    """Execute generic scenarios against real, snapshot-derived trial branches.

    The reference command accepts optional typed ``deltas`` in both world setup
    and intervention documents. Other fields are retained in the trial
    projection as an auditable scenario record; no generic executor pretends to
    understand domain-specific prose.
    """

    def __init__(
        self,
        simulation: SimulationApplication,
        actor_id: uuid.UUID,
        *,
        persist: Callable[[], None] | None = None,
    ) -> None:
        self.simulation = simulation
        self.actor_id = actor_id
        self.persist = persist
        self._persona_versions: dict[uuid.UUID, str] = {}
        registered = {item["command_type"] for item in self.simulation.bus.contracts()}
        if "experiments.scenario.apply" not in registered:
            self.simulation.bus.register(scenario_intervention_definition())

    def bind_persona_version(self, persona_id: uuid.UUID, persona_version: str) -> None:
        existing = self._persona_versions.get(persona_id)
        if existing is not None and existing != persona_version:
            raise ValueError("persona identity was rebound to another immutable version")
        self._persona_versions[persona_id] = persona_version

    def canonical_hash(self, snapshot: SnapshotReference) -> str:
        manifest = self.simulation.snapshots[snapshot.snapshot_id]
        if (
            manifest.world_id != snapshot.world_id
            or manifest.branch_id != snapshot.canonical_branch_id
            or manifest.state_hash != snapshot.state_hash
        ):
            raise ValueError("Snapshot reference does not match immutable manifest")
        canonical = self.simulation.states.get(snapshot.canonical_branch_id)
        if canonical.kind is not BranchKind.CANONICAL:
            raise ValueError("Scenario trials require a canonical source snapshot")
        return canonical.state_hash

    def create_trial_branch(
        self,
        snapshot: SnapshotReference,
        trial_id: uuid.UUID,
        seed: int,
    ) -> TrialBranchReference:
        authority = self.simulation.authority(snapshot.world_id, self.actor_id)
        if "run.branch" not in authority.capabilities:
            raise PermissionError("actor cannot create scenario trial branches in this world")
        manifest = self.simulation.snapshots[snapshot.snapshot_id]
        if manifest.state_hash != snapshot.state_hash:
            raise ValueError("Snapshot reference state hash differs from manifest")
        branch_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:trial-branch:{snapshot.snapshot_id}:{trial_id}:{seed}",
        )
        run_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:trial-run:{snapshot.snapshot_id}:{trial_id}:{seed}",
        )
        try:
            branch = self.simulation.states.get(branch_id)
        except BranchIsolationError:
            snapshot_payload = self.simulation.snapshot_store.load(manifest)
            branch = BranchState(
                world_id=snapshot.world_id,
                branch_id=branch_id,
                kind=BranchKind.TRIAL,
                projections=copy.deepcopy(snapshot_payload["projections"]),
                base_snapshot_hash=snapshot.state_hash,
            )
            self.simulation.states.add(branch)
        else:
            if (
                branch.world_id != snapshot.world_id
                or branch.kind is not BranchKind.TRIAL
                or branch.base_snapshot_hash != snapshot.state_hash
            ):
                raise ValueError("Existing trial branch has a different snapshot origin")
        existing_run = self.simulation.runs.get(run_id)
        if existing_run is None:
            self.simulation.runs[run_id] = RunRecord(
                run_id=run_id,
                world_id=snapshot.world_id,
                branch_id=branch_id,
                kind=RunKind.EVALUATION,
                seed=seed,
            )
        elif (
            existing_run.world_id != snapshot.world_id
            or existing_run.branch_id != branch_id
            or existing_run.kind is not RunKind.EVALUATION
            or existing_run.seed != seed
        ):
            raise ValueError("Existing trial run has a different identity")
        if self.persist is not None:
            self.persist()
        return TrialBranchReference(
            trial_id=trial_id,
            world_id=snapshot.world_id,
            snapshot_id=snapshot.snapshot_id,
            branch_id=branch_id,
            run_id=run_id,
            seed=seed,
        )

    def execute(
        self,
        scenario: ScenarioDefinition,
        branch: TrialBranchReference,
        persona_id: uuid.UUID | None,
        seed: int,
        checkpoint: dict[str, Any],
        cancelled: Callable[[], bool],
    ) -> TrialExecution:
        if cancelled():
            state = self.simulation.states.get(branch.branch_id)
            return TrialExecution(
                status="CANCELLED",
                steps=0,
                final_state=copy.deepcopy(state.projections),
                trial_state_hash=state.state_hash,
                checkpoint=checkpoint,
            )
        deltas: list[StateDelta] = []
        for source in (scenario.world_setup, scenario.intervention):
            raw_deltas = source.get("deltas", ())
            if not isinstance(raw_deltas, (list, tuple)):
                raise ValueError("scenario deltas must be a list")
            deltas.extend(StateDelta.model_validate(item) for item in raw_deltas)
        proposal = CommandProposal(
            command_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"tabletop-dm:scenario-command:{branch.trial_id}",
            ),
            command_type="experiments.scenario.apply",
            world_id=branch.world_id,
            branch_id=branch.branch_id,
            run_id=branch.run_id,
            actor_id=self.actor_id,
            parameters=ScenarioIntervention(
                scenario_id=scenario.scenario_id,
                scenario_version=scenario.version,
                world_setup=scenario.world_setup,
                intervention=scenario.intervention,
                allowed_actions=scenario.allowed_actions,
                stop_conditions=scenario.stop_conditions,
                horizon_steps=scenario.run_horizon_steps,
                deltas=tuple(deltas),
            ).model_dump(mode="python"),
            idempotency_key=f"scenario:{branch.trial_id}:apply",
            correlation_id=branch.trial_id,
            seed=seed,
            persona_version=(
                self._persona_versions.get(persona_id) if persona_id is not None else None
            ),
            policy_version=str(
                scenario.model_assignment.get("policy_version", "reference-policy-1.0.0")
            ),
            model_version=(
                str(scenario.model_assignment["model_version"])
                if "model_version" in scenario.model_assignment
                else None
            ),
        )
        receipt = self.simulation.submit(proposal)
        if self.persist is not None:
            self.persist()
        state = self.simulation.states.get(branch.branch_id)
        return TrialExecution(
            status="COMPLETED",
            steps=1,
            final_state=copy.deepcopy(state.projections),
            trial_state_hash=state.state_hash,
            events=(receipt.event,),
            metrics={"applied_delta_count": len(deltas)},
            checkpoint={"step": 1, "completed": True},
        )
