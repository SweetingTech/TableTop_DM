"""Recover from stalls using this controller's commits and grounded reply lineage."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cognition.context import CharacterContext
from cognition.conversation import ReplySchedule
from cognition.engine import DecisionAction
from kernel.contracts import EventEnvelopeV2
from kernel.control import ControllerState
from kernel.replay import ReplayRecord

_MOVE = "tabletop.spatial.move"
_ATTACK = "tabletop.combat.attack"
_SPEECH = "tabletop.dialogue.speak"
_CONVERSATION_TURNS = 4
RecoveryReason = Literal["no_movement_progress", "repeated_ineffective_attack", "conversation_loop"]


class RecoveryReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["character-recovery-1.0.0"] = "character-recovery-1.0.0"
    reasons: tuple[RecoveryReason, ...]
    skipped_actions: tuple[str, ...]


class CharacterStalled(ValueError):
    """Every candidate consistent with the current plan repeats a known stall."""

    def __init__(self, reason: RecoveryReason) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RecoveryConstraints:
    movement_cycle: tuple[int, int] | None = None
    ineffective_target: str | None = None
    conversation_loop: bool = False

    def blocked(self, action: DecisionAction) -> RecoveryReason | None:
        if self.conversation_loop and action.command_type == _SPEECH:
            return "conversation_loop"
        if action.command_type == _ATTACK and self.ineffective_target is not None:
            if str(action.parameters.get("target_id")) == self.ineffective_target:
                return "repeated_ineffective_attack"
        if action.command_type == _MOVE and self.movement_cycle is not None:
            if (action.parameters.get("dx"), action.parameters.get("dy")) == self.movement_cycle:
                return "no_movement_progress"
        return None

    def eligible(
        self, actions: tuple[DecisionAction, ...]
    ) -> tuple[tuple[DecisionAction, ...], RecoveryReceipt | None]:
        eligible: list[DecisionAction] = []
        skipped: list[str] = []
        reasons: dict[RecoveryReason, None] = {}
        for action in actions:
            reason = self.blocked(action)
            if reason is None:
                eligible.append(action)
            else:
                skipped.append(action.action)
                reasons[reason] = None
        if not reasons:
            return actions, None
        if not eligible:
            raise CharacterStalled(next(iter(reasons)))
        return tuple(eligible), RecoveryReceipt(
            reasons=tuple(reasons), skipped_actions=tuple(skipped)
        )


def _recent_commits(
    history: Sequence[ReplayRecord], controller: ControllerState
) -> tuple[ReplayRecord, ...]:
    found: list[ReplayRecord] = []
    for record in reversed(history):
        proposal = record.proposal
        if (
            (proposal.world_id, proposal.branch_id, proposal.run_id, proposal.embodied_entity_id)
            != controller.key
            or proposal.actor_id != controller.executor_actor_id
            or proposal.decision_authorship != "CHARACTER_POLICY"
            or proposal.control_epoch != controller.epoch
            or not record.result.accepted
        ):
            continue
        if proposal.control_step != controller.step - len(found) - 1:
            break
        found.append(record)
        if len(found) == 4:
            break
    return tuple(found)


def _movement_cycle(
    commits: tuple[ReplayRecord, ...], context: CharacterContext
) -> tuple[int, int] | None:
    if len(commits) != 4 or any(record.proposal.command_type != _MOVE for record in commits):
        return None
    results = [record.result.result for record in commits]
    first, second, third, fourth = (result.get("destination") for result in results)
    if not isinstance(first, dict) or not isinstance(second, dict):
        return None
    if first != third or second != fourth or first == second:
        return None
    observer = next(
        (
            row
            for row in context.scene.perceived_entities
            if row.entity_id == context.scene.observer_entity_id
        ),
        None,
    )
    if observer is None or observer.position is None:
        return None
    x, y = observer.position.x, observer.position.y
    if first != {"x": x, "y": y}:
        return None
    if any(result.get("zone_id") != str(observer.position.zone_id) for result in results):
        return None
    return int(second["x"]) - x, int(second["y"]) - y


def _ineffective_target(commits: tuple[ReplayRecord, ...]) -> str | None:
    recent = commits[:3]
    if len(recent) != 3:
        return None
    target = recent[0].proposal.parameters.get("target_id")
    if not target:
        return None
    if all(
        row.proposal.command_type == _ATTACK
        and row.proposal.parameters.get("target_id") == target
        and row.result.result.get("damage") == 0
        for row in recent
    ):
        return str(target)
    return None


def _conversation_loop(
    reply: ReplySchedule,
    controller: ControllerState,
    read_event: Callable[[uuid.UUID], EventEnvelopeV2 | None],
    observed_event_ids: frozenset[uuid.UUID],
) -> bool:
    # Follow only conversation turns present in the current body's masked experience.
    source_id: uuid.UUID | None = reply.source_event_id
    seen: set[uuid.UUID] = set()
    for _ in range(_CONVERSATION_TURNS):
        if source_id is None or source_id in seen or source_id not in observed_event_ids:
            return False
        source = read_event(source_id)
        if (
            source is None
            or source.event_type != _SPEECH
            or (source.world_id, source.branch_id, source.run_id, source.correlation_id)
            != (*controller.key[:3], reply.correlation_id)
        ):
            return False
        seen.add(source_id)
        source_id = source.causation_id
    return True


def progress_constraints(
    controller: ControllerState,
    context: CharacterContext,
    history: Sequence[ReplayRecord],
    reply: ReplySchedule | None,
    read_event: Callable[[uuid.UUID], EventEnvelopeV2 | None],
) -> RecoveryConstraints:
    commits = _recent_commits(history, controller)
    observed_speech = frozenset(
        observation.source_event_id
        for observation in context.observations
        if isinstance(observation.perceived_payload.get("text"), str)
        and observation.perceived_payload.get("speaker_entity_id")
    )
    return RecoveryConstraints(
        movement_cycle=_movement_cycle(commits, context),
        ineffective_target=_ineffective_target(commits),
        conversation_loop=(
            reply is not None and _conversation_loop(reply, controller, read_event, observed_speech)
        ),
    )
