from __future__ import annotations

import heapq
import itertools
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GoapAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    preconditions: dict[str, Any] = Field(default_factory=dict)
    effects: dict[str, Any] = Field(default_factory=dict)
    cost: float = Field(default=1.0, ge=0)


class PlanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    achieved: bool
    actions: tuple[str, ...] = ()
    total_cost: float = 0.0
    explored_nodes: int = 0
    final_state: dict[str, Any] = Field(default_factory=dict)
    reason: str


class GOAPPlanner:
    """Bounded uniform-cost GOAP with deterministic action and path ordering."""

    VERSION = "goap-1.0.0"

    def plan(
        self,
        initial_state: dict[str, Any],
        goal: dict[str, Any],
        actions: tuple[GoapAction, ...],
        *,
        max_depth: int = 6,
        max_nodes: int = 256,
    ) -> PlanResult:
        if max_depth < 0:
            raise ValueError("max_depth cannot be negative")
        if max_nodes < 1:
            raise ValueError("max_nodes must be positive")
        names = [action.name for action in actions]
        if len(names) != len(set(names)):
            raise ValueError("GOAP action names must be unique")
        if self._satisfies(initial_state, goal):
            return PlanResult(
                achieved=True,
                explored_nodes=0,
                final_state=dict(initial_state),
                reason="goal_already_satisfied",
            )

        ordered_actions = tuple(sorted(actions, key=lambda action: action.name))
        counter = itertools.count()
        initial_key = self._state_key(initial_state)
        queue: list[tuple[float, int, tuple[str, ...], str, int, dict[str, Any]]] = [
            (0.0, 0, (), initial_key, next(counter), dict(initial_state))
        ]
        best_cost: dict[str, float] = {initial_key: 0.0}
        explored = 0

        while queue and explored < max_nodes:
            cost, depth, path, state_key, _, state = heapq.heappop(queue)
            if cost > best_cost.get(state_key, float("inf")):
                continue
            explored += 1
            if self._satisfies(state, goal):
                return PlanResult(
                    achieved=True,
                    actions=path,
                    total_cost=round(cost, 6),
                    explored_nodes=explored,
                    final_state=state,
                    reason="goal_reached",
                )
            if depth >= max_depth:
                continue

            for action in ordered_actions:
                if not self._satisfies(state, action.preconditions):
                    continue
                next_state = dict(state)
                next_state.update(action.effects)
                next_key = self._state_key(next_state)
                next_cost = round(cost + action.cost, 9)
                if next_cost >= best_cost.get(next_key, float("inf")):
                    continue
                best_cost[next_key] = next_cost
                next_path = (*path, action.name)
                heapq.heappush(
                    queue,
                    (
                        next_cost,
                        depth + 1,
                        next_path,
                        next_key,
                        next(counter),
                        next_state,
                    ),
                )

        return PlanResult(
            achieved=False,
            explored_nodes=explored,
            final_state=dict(initial_state),
            reason="search_bound_reached" if queue else "no_plan",
        )

    @staticmethod
    def _satisfies(state: dict[str, Any], requirements: dict[str, Any]) -> bool:
        return all(state.get(key) == value for key, value in requirements.items())

    @staticmethod
    def _state_key(state: dict[str, Any]) -> str:
        return json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
