from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConditionOperator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    IN = "IN"
    CONTAINS = "CONTAINS"
    TRUTHY = "TRUTHY"


class ReflexCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str = Field(min_length=1)
    operator: ConditionOperator = ConditionOperator.EQ
    value: Any = None


class ReflexRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    priority: int = 0
    conditions: tuple[ReflexCondition, ...] = ()


class ReflexDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str
    rule_id: str
    priority: int
    matched_rule_ids: tuple[str, ...]


class ReflexEngine:
    """Evaluates declarative reflex rules with stable priority tie-breaking."""

    VERSION = "reflex-policy-1.0.0"

    def choose(
        self, situation: dict[str, Any], rules: tuple[ReflexRule, ...]
    ) -> ReflexDecision | None:
        identifiers = [rule.rule_id for rule in rules]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Reflex rule IDs must be unique")
        matched = [
            rule
            for rule in rules
            if all(self._matches(situation, condition) for condition in rule.conditions)
        ]
        if not matched:
            return None
        ordered = sorted(matched, key=lambda rule: (-rule.priority, rule.rule_id, rule.action))
        selected = ordered[0]
        return ReflexDecision(
            action=selected.action,
            rule_id=selected.rule_id,
            priority=selected.priority,
            matched_rule_ids=tuple(rule.rule_id for rule in ordered),
        )

    @classmethod
    def _matches(cls, situation: dict[str, Any], condition: ReflexCondition) -> bool:
        found, actual = cls._resolve(situation, condition.path)
        if condition.operator is ConditionOperator.TRUTHY:
            return found and bool(actual)
        if not found:
            return False
        expected = condition.value
        try:
            if condition.operator is ConditionOperator.EQ:
                return actual == expected
            if condition.operator is ConditionOperator.NE:
                return actual != expected
            if condition.operator is ConditionOperator.LT:
                return actual < expected
            if condition.operator is ConditionOperator.LTE:
                return actual <= expected
            if condition.operator is ConditionOperator.GT:
                return actual > expected
            if condition.operator is ConditionOperator.GTE:
                return actual >= expected
            if condition.operator is ConditionOperator.IN:
                return actual in expected
            if condition.operator is ConditionOperator.CONTAINS:
                return expected in actual
        except (TypeError, ValueError):
            return False
        return False

    @staticmethod
    def _resolve(source: dict[str, Any], path: str) -> tuple[bool, Any]:
        current: Any = source
        for component in path.split("."):
            if not isinstance(current, dict) or component not in current:
                return False, None
            current = current[component]
        return True, current
