from __future__ import annotations

import copy
import uuid

import pytest

from cognition.deliberation import DeliberationRequest, DeliberationResponse
from cognition.engine import (
    DecisionAction,
    DecisionRequest,
    LayeredDecisionEngine,
)
from cognition.planning import GoapAction
from cognition.reflexes import ReflexCondition, ReflexRule
from persona.models import CompiledPersona

pytestmark = pytest.mark.unit


def _persona() -> CompiledPersona:
    return CompiledPersona(
        persona_id=uuid.UUID(int=100),
        persona_version="2.0.0",
        compiler_version="test-1",
        identity_summary="A cautious and deliberative traveler.",
        policy_weights={"risk_penalty": 1.5},
        starting_goals=("survive",),
        retrieval_filters=("danger",),
    )


def _request(**updates: object) -> DecisionRequest:
    values: dict[str, object] = {
        "persona": _persona(),
        "world_id": uuid.UUID(int=101),
        "branch_id": uuid.UUID(int=102),
        "run_id": uuid.UUID(int=103),
        "actor_id": uuid.UUID(int=104),
        "embodied_entity_id": uuid.UUID(int=105),
        "seed": 481516,
        "idempotency_key": "decision-1",
        "situation": {"danger": {"fire_nearby": True}, "escaped": False},
        "actions": (
            DecisionAction(
                action="FLEE",
                command_type="tabletop.move",
                parameters={"direction": "away_from_fire"},
                utility_factors={"survival": 0.7},
            ),
            DecisionAction(
                action="NEGOTIATE",
                command_type="tabletop.speak",
                parameters={"intent": "deescalate"},
                utility_factors={"social": 0.69},
            ),
        ),
    }
    values.update(updates)
    return DecisionRequest.model_validate(values)


def test_reflex_wins_and_returns_typed_proposal_without_state_mutation():
    request = _request(
        reflex_rules=(
            ReflexRule(
                rule_id="fire_escape",
                action="FLEE",
                priority=100,
                conditions=(ReflexCondition(path="danger.fire_nearby", value=True),),
            ),
        )
    )
    original = copy.deepcopy(request.situation)

    first = LayeredDecisionEngine().decide(request)
    second = LayeredDecisionEngine().decide(request)

    assert first == second
    assert first.tier == "REFLEX"
    assert first.trace.decision_tier == "REFLEX"
    assert first.trace.rationale is not None
    assert first.proposal.command_type == "tabletop.move"
    assert first.proposal.parameters == {"direction": "away_from_fire"}
    assert first.proposal.decision_trace_id == first.trace.trace_id
    assert first.proposal.persona_version == first.trace.persona_version
    assert first.proposal.policy_version == first.trace.policy_version
    assert request.situation == original


def test_ambiguous_utility_uses_bounded_plan_before_model():
    request = _request(
        utility_margin=1,
        planning_goal={"escaped": True},
        planning_actions=(GoapAction(name="FLEE", effects={"escaped": True}, cost=1),),
    )
    outcome = LayeredDecisionEngine().decide(request)

    assert outcome.tier == "PLANNER"
    assert outcome.trace.plan == ("FLEE",)
    assert outcome.plan is not None and outcome.plan.achieved
    assert outcome.deliberation is None


class _NegotiatingProvider:
    model_version = "local-fixture-1"

    def complete(self, request: DeliberationRequest) -> DeliberationResponse:
        return DeliberationResponse(
            action="NEGOTIATE",
            rationale="Conflicting values make dialogue preferable.",
            confidence=0.75,
        )


def test_novel_decision_uses_typed_model_proposal_with_full_trace():
    request = _request(
        novel_or_ambiguous=True,
        llm_runtime_kind="LOCAL_LLM",
    )
    outcome = LayeredDecisionEngine().decide(request, provider=_NegotiatingProvider())

    assert outcome.tier == "LLM"
    assert outcome.trace.runtime_kind == "LOCAL_LLM"
    assert outcome.trace.model_version == "local-fixture-1"
    assert outcome.trace.prompt_contract_version == "deliberation-prompt-1.0.0"
    assert outcome.trace.chosen_action == "NEGOTIATE"
    assert outcome.proposal.command_type == "tabletop.speak"


def test_missing_model_falls_back_deterministically_to_utility():
    request = _request(novel_or_ambiguous=True)
    outcome = LayeredDecisionEngine().decide(request)
    repeated = LayeredDecisionEngine().decide(request)

    assert outcome == repeated
    assert outcome.tier == "UTILITY"
    assert outcome.deliberation is not None
    assert outcome.deliberation.used_model is False
    assert outcome.trace.fallback_reason == "model_provider_unavailable"
    assert outcome.trace.model_version is None
