"""Bounded personal recovery plans from a character's observed circumstances."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cognition.choice_state import choice_frame
from cognition.context import CharacterContext
from cognition.engine import DecisionAction
from domains.tabletop.spatial.scene import SceneCoordinate
from kernel.control import ControllerState

RECOVERY_COOLDOWN_STEPS = 2


class PlanNeeds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    health: int = Field(ge=0)
    max_health: int = Field(gt=0)
    mana: int = Field(ge=0)
    hunger: int = Field(ge=0)
    fatigue: int = Field(ge=0)


class CharacterPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: uuid.UUID
    goal: Literal["RECOVER_HEALTH"] = "RECOVER_HEALTH"
    version: Literal["character-recovery-plan-1.0.0"] = "character-recovery-plan-1.0.0"
    status: Literal["ACTIVE", "COMPLETED", "INTERRUPTED"] = "ACTIVE"
    action: Literal["WITHDRAW", "MEND"] | None = None
    completed_steps: int = Field(default=0, ge=0, le=2)
    source_command_id: uuid.UUID | None = None
    cooldown_until_step: int | None = Field(default=None, ge=0)
    needs: PlanNeeds


@dataclass(frozen=True)
class PlanSelection:
    plan: CharacterPlan
    allowed_actions: tuple[str, ...] = ()


def _distance(x: int, y: int, other: SceneCoordinate) -> int:
    return max(abs(x - other.x), abs(y - other.y))


def _withdrawal_actions(
    actions: tuple[DecisionAction, ...],
    origin: SceneCoordinate,
    threats: tuple[SceneCoordinate, ...],
) -> tuple[str, ...]:
    baseline = min(_distance(origin.x, origin.y, threat) for threat in threats)
    safer: list[tuple[int, str]] = []
    for action in actions:
        if action.command_type == "tabletop.spatial.move":
            x = origin.x + int(action.parameters["dx"])
            y = origin.y + int(action.parameters["dy"])
            distance = min(_distance(x, y, threat) for threat in threats)
            if distance > baseline:
                safer.append((distance, action.action))
    best = max((distance for distance, _ in safer), default=baseline)
    return tuple(action for distance, action in safer if distance == best)


def select_character_plan(
    context: CharacterContext,
    controller: ControllerState,
    *,
    hunger: int,
    fatigue: int,
    previous: tuple[CharacterPlan, uuid.UUID] | None,
) -> PlanSelection | None:
    """Choose one step and recheck its prerequisites using the current perceived scene."""
    body = next(
        (row for row in context.scene.perceived_entities if row.entity_id == controller.entity_id),
        None,
    )
    if body is None or body.position is None or not body.health or not body.max_health:
        return None
    needs = PlanNeeds(
        health=body.health,
        max_health=body.max_health,
        mana=body.mana or 0,
        hunger=hunger,
        fatigue=fatigue,
    )
    critically_wounded = needs.health * 3 <= needs.max_health
    mend_actions = tuple(
        action.action
        for action in context.actions
        if action.command_type == "tabletop.magic.invoke"
        and action.parameters.get("spell_id") == "MEND"
        and action.parameters.get("target_id") == str(controller.entity_id)
    )
    frame = choice_frame(context.scene, context.observations)
    known = {threat.entity_id for threat in frame.threats} if frame else set()
    visible_threats = tuple(
        row.position
        for row in context.scene.perceived_entities
        if row.entity_id in known and row.knowledge_state == "VISIBLE" and row.position is not None
    )
    in_reach = any(_distance(body.position.x, body.position.y, row) <= 1 for row in visible_threats)

    if previous is not None:
        plan, command_id = previous
        update = {"needs": needs, "source_command_id": command_id}
        if plan.status == "ACTIVE":
            if plan.action == "WITHDRAW" and critically_wounded and mend_actions and not in_reach:
                return PlanSelection(
                    plan.model_copy(update={**update, "action": "MEND", "completed_steps": 1}),
                    mend_actions,
                )
            finished = plan.action == "MEND" or not critically_wounded
            return PlanSelection(
                plan.model_copy(
                    update={
                        **update,
                        "status": "COMPLETED" if finished else "INTERRUPTED",
                        "action": None,
                        "completed_steps": 2 if plan.action == "MEND" else 1,
                        "cooldown_until_step": controller.step + RECOVERY_COOLDOWN_STEPS,
                    }
                )
            )
        if plan.cooldown_until_step is not None and controller.step < plan.cooldown_until_step:
            return PlanSelection(plan.model_copy(update=update))

    if not critically_wounded or not mend_actions or not in_reach:
        return None
    if controller.max_steps - controller.step < 2:
        return None
    withdraw = _withdrawal_actions(context.actions, body.position, visible_threats)
    if not withdraw:
        return None
    plan_id = uuid.uuid5(
        controller.run_id, f"recovery:{controller.entity_id}:{controller.epoch}:{controller.step}"
    )
    return PlanSelection(CharacterPlan(plan_id=plan_id, action="WITHDRAW", needs=needs), withdraw)
