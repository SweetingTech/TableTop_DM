"""Character-policy advice. Producing a proposal never executes it or takes control."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cognition.behavior import BehaviorProfile, weighted_actions
from cognition.character_plans import CharacterPlan, PlanSelection
from cognition.choices import ChoiceProfile, weighted_choices
from cognition.context import CharacterContext, require_projected_experience
from cognition.context import CharacterContextPending as CharacterContextPending
from cognition.conversation import ReplySchedule
from cognition.deliberation import DeliberationProvider
from cognition.dialogue_generation import DialogueProvider, DialogueReceipt, generate_dialogue
from cognition.engine import DecisionOutcome, DecisionRequest, LayeredDecisionEngine
from cognition.models import Observation
from cognition.openai_compatible import DELIBERATION_PROMPT
from cognition.store import MindStore
from domains.tabletop.character_actions import ACTION_CATALOG_VERSION
from domains.tabletop.character_bindings import CharacterBinding
from kernel.application import SimulationApplication
from kernel.contracts import BranchKind
from kernel.control import ControllerState
from kernel.state import stable_hash
from persona.models import CompiledPersona, PersonaPurpose

PROPOSAL_POLICY_VERSION = "character-proposal-policy-1.4.0"


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
    choices: ChoiceProfile | None = None
    dialogue: DialogueReceipt | None = None
    plan: CharacterPlan | None = Field(default=None, exclude_if=lambda value: value is None)
    reply: ReplySchedule | None = Field(default=None, exclude_if=lambda value: value is None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_proposal_lineage(self) -> CharacterProposalReceipt:
        proposal = self.outcome.proposal
        if self.plan is not None and (
            proposal.decision_authorship != "CHARACTER_POLICY"
            or (self.plan.action == "WITHDRAW" and proposal.command_type != "tabletop.spatial.move")
            or (
                self.plan.action == "MEND"
                and (
                    proposal.command_type != "tabletop.magic.invoke"
                    or proposal.parameters.get("spell_id") != "MEND"
                    or proposal.parameters.get("target_id") != str(self.scope.entity_id)
                )
            )
        ):
            raise ValueError("plan step differs from its scoped character proposal")
        if self.dialogue is not None and (
            proposal.command_type != "tabletop.dialogue.speak"
            or self.dialogue.output_hash != stable_hash(proposal.parameters.get("text"))
            or (
                self.dialogue.status == "GENERATED"
                and (
                    proposal.model_version != self.dialogue.model_version
                    or proposal.prompt_contract_version != self.dialogue.version
                    or self.outcome.trace.model_version != self.dialogue.model_version
                    or self.outcome.trace.prompt_contract_version != self.dialogue.version
                    or not self.dialogue.source_event_ids
                )
            )
        ):
            raise ValueError("dialogue receipt differs from its speech proposal")
        if self.reply is not None and (
            proposal.decision_authorship != "CHARACTER_POLICY"
            or proposal.command_type != "tabletop.dialogue.speak"
            or proposal.causation_id != self.reply.source_event_id
            or proposal.correlation_id != self.reply.correlation_id
            or self.reply.speaker_entity_id == self.scope.entity_id
            or (
                self.dialogue is not None
                and self.dialogue.status == "GENERATED"
                and self.reply.source_event_id not in self.dialogue.source_event_ids
            )
        ):
            raise ValueError("scheduled reply differs from its causal speech proposal")
        if self.choices is not None and (
            (
                self.choices.world_id,
                self.choices.branch_id,
                self.choices.run_id,
                self.choices.entity_id,
            )
            != self.scope.key
            or self.choices.character_id != self.character_id
            or self.choices.binding_id != self.binding_id
            or self.choices.context_hash != self.context_hash
            or self.choices.persona_version != self.outcome.trace.persona_version
        ):
            raise ValueError("choice profile lineage is inconsistent")
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
    require_projected_experience(
        world_id=scope.world_id,
        branch_id=scope.branch_id,
        entity_id=scope.entity_id,
        actor_id=actor_id,
        grants=simulation.perceptions.values(),
        event_reader=simulation.events.get,
        observation_exists=lambda item: minds.has_observation(item, branch_id=scope.branch_id),
        recorded_observations=(
            Observation.model_validate(row)
            for row in minds.inspect(scope.entity_id, branch_id=scope.branch_id)["observations"]
        ),
        stored_confidence_precision=simulation.durable_repository is not None,
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
    choices: ChoiceProfile | None = None,
    dialogue_provider: DialogueProvider | None = None,
    plan: PlanSelection | None = None,
    deliberation_provider: DeliberationProvider | None = None,
    deliberation_kind: Literal["LOCAL_LLM", "HOSTED_LLM"] = "HOSTED_LLM",
    reply: ReplySchedule | None = None,
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
    actions = weighted_choices(
        weighted_actions(context.actions, behavior) if behavior else context.actions,
        choices,
    )
    if plan is not None and plan.allowed_actions:
        actions = tuple(action for action in actions if action.action in plan.allowed_actions)
    if reply is not None:
        actions = tuple(
            action.model_copy(
                update={"utility_factors": {**action.utility_factors, "reply_due": 0.35}}
            )
            if action.command_type == "tabletop.dialogue.speak"
            else action
            for action in actions
        )
    use_deliberation = deliberation_provider is not None and not (plan and plan.allowed_actions)
    request = DecisionRequest(
        persona=profile,
        world_id=scope.world_id,
        branch_id=scope.branch_id,
        run_id=scope.run_id,
        actor_id=actor_id,
        embodied_entity_id=scope.entity_id,
        seed=seed,
        idempotency_key="character-proposal:" + str(decision_id),
        situation=context.situation(),
        actions=actions,
        allow_llm=use_deliberation,
        utility_margin=0.15 if use_deliberation else 0,
        llm_runtime_kind=deliberation_kind,
        prompt_contract_version=DELIBERATION_PROMPT,
    )
    decision_engine = engine or LayeredDecisionEngine()
    outcome = (
        decision_engine.decide(request, provider=deliberation_provider)
        if use_deliberation
        else decision_engine.decide(request)
    )
    scheduled = reply if outcome.proposal.command_type == "tabletop.dialogue.speak" else None
    if scheduled is not None:
        outcome = outcome.model_copy(
            update={
                "proposal": outcome.proposal.model_copy(
                    update={
                        "causation_id": scheduled.source_event_id,
                        "correlation_id": scheduled.correlation_id,
                    }
                )
            }
        )
    dialogue = None
    if dialogue_provider is not None and outcome.proposal.command_type == "tabletop.dialogue.speak":
        text, dialogue = generate_dialogue(
            context,
            outcome.proposal.parameters,
            profile.deep_traits,
            seed,
            dialogue_provider,
            reply_event_id=scheduled.source_event_id if scheduled is not None else None,
        )
        proposed = outcome.proposal.model_copy(
            update={"parameters": {**outcome.proposal.parameters, "text": text, "claims": []}}
        )
        if dialogue.status == "GENERATED":
            proposed = proposed.model_copy(
                update={
                    "model_version": dialogue.model_version,
                    "prompt_contract_version": dialogue.version,
                }
            )
            outcome = outcome.model_copy(
                update={
                    "tier": "LLM",
                    "trace": outcome.trace.model_copy(
                        update={
                            "decision_tier": "LLM",
                            "runtime_kind": dialogue.runtime_kind,
                            "model_version": dialogue.model_version,
                            "prompt_contract_version": dialogue.version,
                            "rationale": "Grounded speech after policy intent selection.",
                        }
                    ),
                }
            )
        outcome = outcome.model_copy(update={"proposal": proposed})
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
                "control_attempt": controller.failures or None,
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
        choices=choices,
        dialogue=dialogue,
        plan=plan.plan if plan is not None else None,
        reply=scheduled,
    )


class CharacterProposalRepository(Protocol):
    def find_decision(
        self, scope: CharacterProposalScope, actor_id: uuid.UUID, decision_id: uuid.UUID
    ) -> CharacterProposalReceipt | None: ...

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

    def find_decision(
        self, scope: CharacterProposalScope, actor_id: uuid.UUID, decision_id: uuid.UUID
    ) -> CharacterProposalReceipt | None:
        with self._lock:
            for receipt in self._rows.values():
                if (receipt.scope, receipt.actor_id, receipt.decision_id) == (
                    scope,
                    actor_id,
                    decision_id,
                ):
                    return receipt.model_copy(deep=True)
        return None

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
