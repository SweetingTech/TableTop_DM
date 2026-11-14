"""Character-policy advice. Producing a proposal never executes it or takes control."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cognition.behavior import BehaviorProfile, weighted_actions
from cognition.context import NON_SENSORY_TAGS, CharacterContext
from cognition.engine import DecisionOutcome, DecisionRequest, LayeredDecisionEngine
from cognition.perception import PerceptionEngine, PerceptionProfile
from cognition.store import MindStore
from domains.tabletop.character_actions import ACTION_CATALOG_VERSION
from domains.tabletop.character_bindings import CharacterBinding
from kernel.application import SimulationApplication
from kernel.contracts import BranchKind
from kernel.control import ControllerState
from kernel.state import stable_hash
from persona.models import CompiledPersona, PersonaPurpose

PROPOSAL_POLICY_VERSION = "character-proposal-policy-1.1.0"


class CharacterProposalScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID

    @property
    def key(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
        return self.world_id, self.branch_id, self.run_id, self.entity_id


class CharacterProposalReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    decision_id: uuid.UUID
    scope: CharacterProposalScope
    actor_id: uuid.UUID
    idempotency_key: str = Field(min_length=1, max_length=200)
    binding_id: uuid.UUID
    character_id: uuid.UUID
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_version: str
    projection_version: int = Field(ge=0)
    seed: int = Field(ge=0, le=(1 << 63) - 1)
    run_seed: int | None
    compiler_version: str
    catalog_version: str = ACTION_CATALOG_VERSION
    proposal_policy_version: str = PROPOSAL_POLICY_VERSION
    authorship: Literal["CHARACTER_POLICY"] = "CHARACTER_POLICY"
    execution_mode: Literal["PROPOSAL_ONLY"] = "PROPOSAL_ONLY"
    committed: Literal[False] = False
    outcome: DecisionOutcome
    behavior: BehaviorProfile | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_proposal_lineage(self) -> CharacterProposalReceipt:
        proposal = self.outcome.proposal
        if self.behavior is not None and (
            (
                self.behavior.world_id,
                self.behavior.branch_id,
                self.behavior.run_id,
                self.behavior.entity_id,
            )
            != self.scope.key
            or self.behavior.character_id != self.character_id
            or self.behavior.binding_id != self.binding_id
            or self.behavior.context_hash != self.context_hash
            or self.behavior.persona_version != self.outcome.trace.persona_version
        ):
            raise ValueError("behavior profile lineage is inconsistent with its character decision")
        if (
            (proposal.world_id, proposal.branch_id, proposal.run_id, proposal.embodied_entity_id)
            != self.scope.key
            or proposal.actor_id != self.actor_id
            or proposal.seed != self.seed
            or proposal.decision_trace_id != self.decision_id
            or self.outcome.trace.trace_id != self.decision_id
            or self.outcome.trace.seed != self.seed
        ):
            raise ValueError("character proposal receipt lineage is inconsistent")
        return self


class CharacterContextPending(ValueError):
    """Retry advice generation after the dependent subjective projection catches up."""


def require_character_proposal_authority(
    simulation: SimulationApplication, scope: CharacterProposalScope, actor_id: uuid.UUID
) -> None:
    state = simulation.states.get(scope.branch_id)
    run = simulation.runs.get(scope.run_id)
    entity = simulation.entities.get((scope.branch_id, scope.entity_id))
    if (
        state.world_id != scope.world_id
        or run is None
        or (run.world_id, run.branch_id) != (scope.world_id, scope.branch_id)
        or entity is None
        or entity.world_id != scope.world_id
    ):
        raise ValueError("character proposal scope is unavailable")
    actor = simulation.authority(scope.world_id, actor_id)
    required = frozenset(
        {
            "action.propose",
            "entity.act",
            "action.commit" if state.kind is BranchKind.CANONICAL else "action.propose",
        }
    )
    if scope.entity_id not in actor.controlled_entity_ids or not actor.has_capabilities(required):
        raise PermissionError("actor cannot propose for this character")


def require_projected_character_experience(
    simulation: SimulationApplication,
    minds: MindStore,
    scope: CharacterProposalScope,
    actor_id: uuid.UUID,
) -> None:
    profile = PerceptionProfile(observer_entity_id=scope.entity_id, observer_actor_id=actor_id)
    for grant in simulation.perceptions.values():
        if (grant.world_id, grant.branch_id, grant.observer_entity_id) != (
            scope.world_id,
            scope.branch_id,
            scope.entity_id,
        ):
            continue
        event = simulation.events.get(grant.event_id)
        if event is None or (event.world_id, event.branch_id) != (scope.world_id, scope.branch_id):
            raise CharacterContextPending(
                "character observations are still updating; retry this proposal request"
            )
        if NON_SENSORY_TAGS.intersection(event.domain_tags):
            continue
        expected = PerceptionEngine().observe(event, profile, grant=grant)
        if expected is not None and not minds.has_observation(
            expected.observation_id, branch_id=scope.branch_id
        ):
            raise CharacterContextPending(
                "character observations are still updating; retry this proposal request"
            )


def propose_for_character(
    *,
    scope: CharacterProposalScope,
    actor_id: uuid.UUID,
    key: str,
    run_seed: int | None,
    context: CharacterContext,
    binding: CharacterBinding,
    profile: CompiledPersona,
    engine: LayeredDecisionEngine | None = None,
    controller: ControllerState | None = None,
    human_epoch: int | None = None,
    behavior: BehaviorProfile | None = None,
) -> CharacterProposalReceipt:
    if (
        binding.scope != scope.key
        or (context.scene.world_id, context.scene.branch_id, context.scene.observer_entity_id)
        != (scope.world_id, scope.branch_id, scope.entity_id)
        or profile.purpose is not PersonaPurpose.CHARACTER
        or context.identity is None
        or (profile.persona_id, profile.persona_version, profile.compiler_version)
        != (binding.persona_id, str(binding.persona_version_id), binding.compiler_version)
    ):
        raise ValueError("a valid pinned character context is required")
    if not context.actions:
        raise ValueError("no supported character actions are currently available")
    identity = {
        "policy": PROPOSAL_POLICY_VERSION,
        "scope": scope.model_dump(mode="json"),
        "actor": str(actor_id),
        "key": key,
    }
    decision_id = uuid.uuid5(
        uuid.NAMESPACE_URL, "tabletop-dm:character-proposal:" + stable_hash(identity)
    )
    seed = int(
        stable_hash({**identity, "run_seed": run_seed if run_seed is not None else 0})[:16], 16
    ) & ((1 << 63) - 1)
    outcome = (engine or LayeredDecisionEngine()).decide(
        DecisionRequest(
            persona=profile,
            world_id=scope.world_id,
            branch_id=scope.branch_id,
            run_id=scope.run_id,
            actor_id=actor_id,
            embodied_entity_id=scope.entity_id,
            seed=seed,
            idempotency_key="character-proposal:" + str(decision_id),
            situation=context.situation(),
            actions=weighted_actions(context.actions, behavior) if behavior else context.actions,
            allow_llm=False,
            utility_margin=0,
        )
    )
    trace = outcome.trace.model_copy(update={"trace_id": decision_id})
    proposal = outcome.proposal.model_copy(
        update={
            "command_id": uuid.uuid5(decision_id, "command"),
            "decision_trace_id": decision_id,
            "control_epoch": human_epoch,
            "input_origin": "POLICY_ADVICE",
        }
    )
    if controller is not None:
        proposal = proposal.model_copy(
            update={
                "control_epoch": controller.epoch,
                "control_step": controller.step,
                "decision_authorship": "CHARACTER_POLICY",
            }
        )
    outcome = outcome.model_copy(update={"trace": trace, "proposal": proposal})
    return CharacterProposalReceipt(
        decision_id=decision_id,
        scope=scope,
        actor_id=actor_id,
        idempotency_key=key,
        binding_id=binding.binding_id,
        character_id=binding.character_id,
        context_hash=context.evidence_hash,
        context_version=context.context_version,
        projection_version=context.scene.projection_version,
        seed=seed,
        run_seed=run_seed,
        compiler_version=binding.compiler_version,
        outcome=outcome,
        behavior=behavior,
    )


class CharacterProposalRepository(Protocol):
    def get_or_create(
        self,
        scope: CharacterProposalScope,
        actor_id: uuid.UUID,
        key: str,
        factory: Callable[[], CharacterProposalReceipt],
    ) -> CharacterProposalReceipt: ...


class InMemoryCharacterProposals:
    def __init__(self) -> None:
        self._rows: dict[tuple, CharacterProposalReceipt] = {}
        self._lock = threading.RLock()

    def get_or_create(
        self,
        scope: CharacterProposalScope,
        actor_id: uuid.UUID,
        key: str,
        factory: Callable[[], CharacterProposalReceipt],
    ) -> CharacterProposalReceipt:
        with self._lock:
            identity = (*scope.key, actor_id, key)
            if identity not in self._rows:
                receipt = factory()
                if (receipt.scope, receipt.actor_id, receipt.idempotency_key) != (
                    scope,
                    actor_id,
                    key,
                ):
                    raise ValueError("character proposal receipt scope differs from its request")
                self._rows[identity] = receipt.model_copy(deep=True)
            return self._rows[identity].model_copy(deep=True)
