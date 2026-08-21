from __future__ import annotations

import copy
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cognition.beliefs import BeliefClaim, BeliefEngine, BeliefRevision
from cognition.deliberation import (
    DeliberationProvider,
    DeliberationRequest,
    DeliberationResult,
    TypedDeliberationGateway,
)
from cognition.memory import MemoryEngine
from cognition.models import (
    Belief,
    BeliefEvidence,
    Memory,
    Observation,
    ObservationDisposition,
)
from cognition.perception import PerceptionEngine, PerceptionProfile
from cognition.planning import GoapAction, GOAPPlanner, PlanResult
from cognition.policy import ActionOption, UtilityPolicy
from cognition.reflexes import ReflexDecision, ReflexEngine, ReflexRule
from kernel.contracts import (
    CommandProposal,
    DecisionTrace,
    EventEnvelopeV2,
)
from kernel.perception_contracts import PerceptionGrant
from kernel.state import stable_hash
from persona.models import CompiledPersona


class SubjectiveUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation: Observation | None
    belief_revision: BeliefRevision | None
    memory: Memory | None
    evidence: tuple[BeliefEvidence, ...] = ()
    disposition: ObservationDisposition = Field(default_factory=ObservationDisposition)


class SubjectiveStatePipeline:
    """Pure event-to-subjective-state pipeline; callers choose how to persist results."""

    def __init__(self) -> None:
        self.perception = PerceptionEngine()
        self.beliefs = BeliefEngine()
        self.memories = MemoryEngine()

    def process(
        self,
        event: EventEnvelopeV2,
        profile: PerceptionProfile,
        *,
        grant: PerceptionGrant,
        existing_beliefs: tuple[Belief, ...] = (),
        claims: tuple[BeliefClaim, ...] | None = None,
        memory_summary: str | None = None,
        emotional_weight: float = 0,
        importance: float = 0.5,
        memory_visibility: str = "PRIVATE",
        disposition: ObservationDisposition | None = None,
    ) -> SubjectiveUpdate:
        disposition = disposition or self._disposition(event)
        observation = self.perception.observe(event, profile, grant=grant)
        if observation is None:
            return SubjectiveUpdate(
                observation=None,
                belief_revision=None,
                memory=None,
                disposition=disposition,
            )
        effective_claims = (
            self.beliefs.claims_from_observation(observation) if claims is None else claims
        )
        revision = (
            self.beliefs.revise(observation, effective_claims, existing_beliefs)
            if disposition.revise_beliefs
            else None
        )
        memory = None
        if disposition.create_memory:
            memory = self.memories.record(
                observation,
                summary=memory_summary,
                emotional_weight=emotional_weight
                if emotional_weight != 0
                else disposition.emotional_weight,
                importance=importance if importance != 0.5 else disposition.importance,
                visibility=memory_visibility,
            )
        evidence = self._evidence(event, observation, revision, grant)
        return SubjectiveUpdate(
            observation=observation,
            belief_revision=revision,
            memory=memory,
            evidence=evidence,
            disposition=disposition,
        )

    @staticmethod
    def _disposition(event: EventEnvelopeV2) -> ObservationDisposition:
        tags = set(event.domain_tags)
        if "movement" in tags:
            return ObservationDisposition(create_memory=False, importance=0.05)
        if "speech" in tags or "dialogue" in tags:
            return ObservationDisposition(create_memory=True, importance=0.45)
        if tags.intersection({"combat", "betrayal", "injury", "discovery"}):
            return ObservationDisposition(create_memory=True, importance=0.85)
        return ObservationDisposition(create_memory=True, importance=0.5)

    @staticmethod
    def _evidence(
        event: EventEnvelopeV2,
        observation: Observation,
        revision: BeliefRevision | None,
        grant: PerceptionGrant,
    ) -> tuple[BeliefEvidence, ...]:
        if revision is None:
            return ()
        is_testimony = "testimony" in event.domain_tags or "speech" in event.domain_tags
        evidence_type = "TESTIMONY" if is_testimony else "DIRECT_OBSERVATION"
        immediate_source = None
        if is_testimony and event.payload.get("speaker_entity_id"):
            immediate_source = uuid.UUID(str(event.payload["speaker_entity_id"]))
        active = [
            belief
            for belief in revision.active_beliefs
            if belief.source_observation_id == observation.observation_id
        ]
        return tuple(
            BeliefEvidence(
                evidence_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"tabletop-dm:evidence:{observation.observation_id}:{belief.belief_id}",
                ),
                world_id=event.world_id,
                branch_id=event.branch_id,
                entity_id=observation.observer_entity_id,
                belief_id=belief.belief_id,
                source_observation_id=observation.observation_id,
                evidence_type=evidence_type,
                immediate_source_entity_id=immediate_source,
                direct_witness=not is_testimony,
                confidence_modifier=grant.confidence,
                created_at=observation.observed_at,
            )
            for belief in sorted(active, key=lambda item: str(item.belief_id))
        )


class DecisionAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str = Field(min_length=1)
    command_type: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    parameters: dict[str, Any] = Field(default_factory=dict)
    utility_factors: dict[str, float] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona: CompiledPersona
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    actor_id: uuid.UUID
    embodied_entity_id: uuid.UUID | None = None
    interaction_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    causation_id: uuid.UUID | None = None
    seed: int
    idempotency_key: str = Field(min_length=1, max_length=200)
    situation: dict[str, Any] = Field(default_factory=dict)
    actions: tuple[DecisionAction, ...] = Field(min_length=1)
    reflex_rules: tuple[ReflexRule, ...] = ()
    planning_goal: dict[str, Any] = Field(default_factory=dict)
    planning_actions: tuple[GoapAction, ...] = ()
    planner_max_depth: int = Field(default=6, ge=0, le=32)
    planner_max_nodes: int = Field(default=256, ge=1, le=10_000)
    utility_margin: float = Field(default=0.15, ge=0)
    novel_or_ambiguous: bool = False
    allow_llm: bool = True
    llm_runtime_kind: Literal["LOCAL_LLM", "HOSTED_LLM"] = "HOSTED_LLM"
    prompt_contract_version: str = "deliberation-prompt-1.0.0"

    @field_validator("actions")
    @classmethod
    def action_names_must_be_unique(
        cls, value: tuple[DecisionAction, ...]
    ) -> tuple[DecisionAction, ...]:
        names = [action.action for action in value]
        if len(names) != len(set(names)):
            raise ValueError("Decision action names must be unique")
        return value


class DecisionOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    tier: Literal["REFLEX", "UTILITY", "PLANNER", "LLM"]
    trace: DecisionTrace
    proposal: CommandProposal
    reflex: ReflexDecision | None = None
    plan: PlanResult | None = None
    deliberation: DeliberationResult | None = None


class LayeredDecisionEngine:
    """Reflex, utility, bounded planning, and typed deliberation proposal engine."""

    VERSION = "layered-cognition-1.0.0"

    def __init__(self) -> None:
        self.reflexes = ReflexEngine()
        self.utility = UtilityPolicy()
        self.planner = GOAPPlanner()
        self.deliberation = TypedDeliberationGateway()

    def decide(
        self,
        request: DecisionRequest,
        *,
        provider: DeliberationProvider | None = None,
    ) -> DecisionOutcome:
        actions = {action.action: action for action in request.actions}
        situation_before = copy.deepcopy(request.situation)
        utility_trace = self.utility.choose(
            request.persona,
            request.seed,
            tuple(
                ActionOption(action.action, dict(action.utility_factors))
                for action in request.actions
            ),
        )
        candidates = utility_trace.candidates
        scores = {candidate.action: candidate.score for candidate in candidates}

        reflex = self.reflexes.choose(request.situation, request.reflex_rules)
        plan: PlanResult | None = None
        deliberation: DeliberationResult | None = None
        rationale: str
        fallback_reason: str | None = None
        plan_actions: tuple[str, ...] = ()

        if reflex is not None:
            if reflex.action not in actions:
                raise ValueError(f"Reflex {reflex.rule_id} selected unknown action {reflex.action}")
            chosen = reflex.action
            tier: Literal["REFLEX", "UTILITY", "PLANNER", "LLM"] = "REFLEX"
            runtime_kind = "DETERMINISTIC"
            rationale = f"Reflex rule {reflex.rule_id} matched at priority {reflex.priority}."
        else:
            ordered = sorted(candidates, key=lambda item: (-item.score, item.action))
            margin = float("inf") if len(ordered) == 1 else ordered[0].score - ordered[1].score
            utility_is_clear = not request.novel_or_ambiguous and margin >= request.utility_margin
            if utility_is_clear:
                chosen = ordered[0].action
                tier = "UTILITY"
                runtime_kind = "UTILITY"
                rationale = f"Utility winner exceeded the decision margin ({margin:.6f})."
            else:
                if request.planning_goal and request.planning_actions:
                    plan = self.planner.plan(
                        request.situation,
                        request.planning_goal,
                        request.planning_actions,
                        max_depth=request.planner_max_depth,
                        max_nodes=request.planner_max_nodes,
                    )
                if plan is not None and plan.achieved and plan.actions:
                    if plan.actions[0] not in actions:
                        raise ValueError(f"Planner selected unknown action {plan.actions[0]}")
                    chosen = plan.actions[0]
                    plan_actions = plan.actions
                    tier = "PLANNER"
                    runtime_kind = "PLANNER"
                    rationale = (
                        f"Bounded planner found a {len(plan.actions)}-step plan "
                        f"with cost {plan.total_cost:.6f}."
                    )
                elif request.allow_llm:
                    deliberation = self.deliberation.decide(
                        DeliberationRequest(
                            identity_summary=request.persona.identity_summary,
                            situation=request.situation,
                            allowed_actions=tuple(sorted(actions)),
                            seed=request.seed,
                            prompt_contract_version=request.prompt_contract_version,
                        ),
                        scores,
                        provider,
                    )
                    chosen = deliberation.response.action
                    rationale = deliberation.response.rationale
                    fallback_reason = deliberation.fallback_reason
                    if deliberation.used_model:
                        tier = "LLM"
                        runtime_kind = request.llm_runtime_kind
                    else:
                        tier = "UTILITY"
                        runtime_kind = "UTILITY"
                else:
                    chosen = ordered[0].action
                    tier = "UTILITY"
                    runtime_kind = "UTILITY"
                    fallback_reason = "llm_disabled"
                    rationale = "Ambiguous decision resolved by deterministic utility policy."

        trace_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    "tabletop-dm:layered-trace",
                    self.VERSION,
                    str(request.persona.persona_id),
                    request.persona.persona_version,
                    str(request.seed),
                    tier,
                    chosen,
                    stable_hash([candidate.model_dump() for candidate in candidates]),
                    stable_hash(plan_actions),
                )
            ),
        )
        trace = DecisionTrace(
            trace_id=trace_id,
            persona_id=request.persona.persona_id,
            persona_version=request.persona.persona_version,
            policy_version=self.VERSION,
            runtime_kind=runtime_kind,
            seed=request.seed,
            candidates=candidates,
            chosen_action=chosen,
            decision_tier=tier,
            rationale=rationale,
            fallback_reason=fallback_reason,
            plan=plan_actions,
            prompt_contract_version=(
                request.prompt_contract_version if deliberation is not None else None
            ),
            model_version=(
                deliberation.model_version
                if deliberation is not None and deliberation.used_model
                else None
            ),
        )
        action = actions[chosen]
        correlation_id = request.correlation_id or uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:correlation:{request.run_id}:{request.idempotency_key}",
        )
        proposal = CommandProposal(
            command_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"tabletop-dm:proposal:{request.run_id}:{request.actor_id}:"
                f"{request.idempotency_key}:{trace_id}",
            ),
            command_type=action.command_type,
            world_id=request.world_id,
            branch_id=request.branch_id,
            run_id=request.run_id,
            interaction_id=request.interaction_id,
            actor_id=request.actor_id,
            embodied_entity_id=request.embodied_entity_id,
            parameters=copy.deepcopy(action.parameters),
            idempotency_key=request.idempotency_key,
            correlation_id=correlation_id,
            causation_id=request.causation_id,
            seed=request.seed,
            decision_trace_id=trace.trace_id,
            persona_version=trace.persona_version,
            policy_version=trace.policy_version,
            prompt_contract_version=trace.prompt_contract_version,
            model_version=trace.model_version,
        )
        if request.situation != situation_before:
            raise RuntimeError("Decision evaluation mutated the supplied situation")
        return DecisionOutcome(
            tier=tier,
            trace=trace,
            proposal=proposal,
            reflex=reflex,
            plan=plan,
            deliberation=deliberation,
        )
