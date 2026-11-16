"""Finite physical conditions and clock boundaries, separate from permanent body conditions."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from domains.tabletop.action_time import ACTION_TIME, ROUND_SECONDS, expire_guards
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

Condition = Literal[
    "stunned", "incapacitated", "unconscious", "paralyzed", "poisoned", "frightened"
]


class TimedCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    condition: Condition
    started_seconds: int = Field(ge=0)
    expires_seconds: int = Field(ge=1)
    source_command_id: uuid.UUID
    run_id: uuid.UUID

    @model_validator(mode="after")
    def forward_expiry(self) -> TimedCondition:
        if self.expires_seconds <= self.started_seconds:
            raise ValueError("condition expiry must follow its start")
        return self


class ConditionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: uuid.UUID
    condition: Condition
    duration_seconds: int = Field(ge=1, le=86400)

    @field_validator("condition", mode="before")
    @classmethod
    def normalize_condition(cls, value: object) -> object:
        return value.casefold() if isinstance(value, str) else value


class ConditionResult(BaseModel):
    effect_id: uuid.UUID
    target_id: uuid.UUID
    condition: Condition
    expires_seconds: int = Field(ge=1)


def timed_conditions(body: dict) -> dict[str, TimedCondition]:
    return {
        key: TimedCondition.model_validate(value)
        for key, value in sorted(body.get("timed_conditions", {}).items())
    }


def clock_now(state: BranchState, run_id: uuid.UUID) -> int | None:
    clock = state.projections.get("tabletop.clock", {}).get("singleton")
    if clock is None:
        return None
    if str(clock["run_id"]) != str(run_id):
        raise ValueError("effect requires the current run's clock")
    return int(clock["seconds"])


def apply_condition(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ConditionRequest.model_validate(proposal.parameters)
    now = clock_now(state, proposal.run_id)
    body = state.projections.get("tabletop.entities", {}).get(str(request.target_id))
    if now is None or body is None:
        raise ValueError("timed conditions require this branch's clock and body")
    active = timed_conditions(body)
    if len(active) >= 32:
        raise ValueError("body timed-condition limit reached")
    identity = uuid.uuid5(
        proposal.run_id, f"condition:{proposal.actor_id}:{proposal.idempotency_key}"
    )
    effect = TimedCondition(
        condition=request.condition,
        started_seconds=now,
        expires_seconds=now + request.duration_seconds,
        source_command_id=proposal.command_id,
        run_id=proposal.run_id,
    )
    active[str(identity)] = effect
    result = ConditionResult(
        effect_id=identity,
        target_id=request.target_id,
        condition=request.condition,
        expires_seconds=effect.expires_seconds,
    )
    return CommandResult(
        result=result.model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.target_id,
                values={
                    "timed_conditions": {
                        key: value.model_dump(mode="json") for key, value in sorted(active.items())
                    }
                },
            ),
        ),
        domain_tags=("operator", "condition_configuration"),
    )


def anchor_legacy_blessings(state: BranchState, now: int) -> None:
    for body in state.projections.get("tabletop.entities", {}).values():
        for blessing in body.get("blessings", ()):
            if "expires_seconds" not in blessing:
                blessing["expires_seconds"] = (
                    now + max(0, int(blessing["remaining_turns"])) * ROUND_SECONDS
                )


def boundaries(state: BranchState, start: int, until: int) -> tuple[int, ...]:
    from domains.tabletop.recovery import boundaries as recovery_boundaries

    points = {until, *recovery_boundaries(state, start, until)}
    for body in state.projections.get("tabletop.entities", {}).values():
        points.update(row.expires_seconds for row in timed_conditions(body).values())
        points.update(
            int(row["expires_seconds"])
            for row in body.get("blessings", ())
            if "expires_seconds" in row
        )
    for row in state.projections.get(ACTION_TIME, {}).values():
        points.add(int(row["ready_seconds"]))
        if "guard_expires_seconds" in row:
            points.add(int(row["guard_expires_seconds"]))
    return tuple(sorted(point for point in points if start < point <= until))


def expire(state: BranchState, now: int) -> None:
    from domains.tabletop.recovery import advance as advance_recovery

    advance_recovery(state, now)
    expire_guards(state, now)
    for body in state.projections.get("tabletop.entities", {}).values():
        if "timed_conditions" in body:
            body["timed_conditions"] = {
                key: row.model_dump(mode="json")
                for key, row in timed_conditions(body).items()
                if row.expires_seconds > now
            }
        if "blessings" in body:
            remaining = []
            for original in body["blessings"]:
                row = dict(original)
                if "expires_seconds" in row:
                    left = int(row["expires_seconds"]) - now
                    if left <= 0:
                        continue
                    row["remaining_turns"] = (left + ROUND_SECONDS - 1) // ROUND_SECONDS
                remaining.append(row)
            body["blessings"] = remaining


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.condition.apply",
        required_capabilities=frozenset({"action.propose", "entity.control"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=apply_condition,
        request_model=ConditionRequest,
        result_model=ConditionResult,
    )
