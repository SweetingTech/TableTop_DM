from __future__ import annotations

import pytest

from cognition.deliberation import (
    DeliberationRequest,
    DeliberationResponse,
    TypedDeliberationGateway,
)
from cognition.planning import GoapAction, GOAPPlanner

pytestmark = pytest.mark.unit


def test_goap_finds_lowest_cost_plan_with_stable_ordering():
    actions = (
        GoapAction(
            name="STEAL_MEDICINE",
            effects={"has_medicine": True},
            cost=8,
        ),
        GoapAction(
            name="BUY_MEDICINE",
            preconditions={"has_money": True},
            effects={"has_medicine": True},
            cost=1,
        ),
        GoapAction(name="BORROW_MONEY", effects={"has_money": True}, cost=2),
    )
    planner = GOAPPlanner()

    first = planner.plan(
        {"has_money": False, "has_medicine": False},
        {"has_medicine": True},
        actions,
    )
    second = planner.plan(
        {"has_money": False, "has_medicine": False},
        {"has_medicine": True},
        tuple(reversed(actions)),
    )

    assert first == second
    assert first.achieved is True
    assert first.actions == ("BORROW_MONEY", "BUY_MEDICINE")
    assert first.total_cost == 3


def test_goap_honors_search_bounds():
    result = GOAPPlanner().plan(
        {"a": False},
        {"goal": True},
        (GoapAction(name="SET_A", effects={"a": True}),),
        max_depth=1,
        max_nodes=1,
    )
    assert result.achieved is False
    assert result.reason == "search_bound_reached"


class _ValidProvider:
    model_version = "test-model-1"

    def complete(self, request: DeliberationRequest) -> DeliberationResponse:
        return DeliberationResponse(
            action="NEGOTIATE",
            rationale="The risk is high and a peaceful option remains.",
            confidence=0.8,
        )


class _DisallowedProvider:
    model_version = "test-model-bad"

    def complete(self, request: DeliberationRequest) -> dict[str, object]:
        return {"action": "MUTATE_WORLD", "rationale": "Because.", "confidence": 1}


def test_typed_deliberation_accepts_allowed_proposal_and_rejects_disallowed_one():
    request = DeliberationRequest(
        identity_summary="A cautious negotiator.",
        situation={"threat": "uncertain"},
        allowed_actions=("FLEE", "NEGOTIATE"),
        seed=77,
    )
    gateway = TypedDeliberationGateway()

    valid = gateway.decide(request, {"FLEE": 0.4, "NEGOTIATE": 0.6}, _ValidProvider())
    rejected = gateway.decide(request, {"FLEE": 0.7, "NEGOTIATE": 0.6}, _DisallowedProvider())

    assert valid.used_model is True
    assert valid.response.action == "NEGOTIATE"
    assert valid.model_version == "test-model-1"
    assert rejected.used_model is False
    assert rejected.response.action == "FLEE"
    assert rejected.fallback_reason == "model_selected_disallowed_action:MUTATE_WORLD"
