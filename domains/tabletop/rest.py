"""Versioned recovery from uninterrupted canonical rest, independent of the controller."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.action_time import UNTIMED_COMMANDS, wait_seconds
from domains.tabletop.activities import ACTIVITIES, Activity, ActivityOutputs, position, seconds
from domains.tabletop.rules import incapacitated
from kernel.command_bus import CommandDefinition, CommandHandler
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

REST_VERSION: Literal["tabletop-rest-1.0.0"] = "tabletop-rest-1.0.0"
SHORT_SECONDS = 3600
LONG_SECONDS = 28800
LONG_INTERVAL = 86400


class RestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["SHORT", "LONG"]


class RestResult(BaseModel):
    activity_id: uuid.UUID
    kind: Literal["SHORT", "LONG"]
    duration_seconds: int


class ResourceLimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID
    max_hp: int = Field(ge=1, le=100000)
    max_mana: int = Field(ge=0, le=100000)


class ResourceLimitsResult(BaseModel):
    entity_id: uuid.UUID
    max_hp: int
    max_mana: int


class RestProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rules_version: Literal["tabletop-rest-1.0.0"] = REST_VERSION
    elapsed_seconds: int = Field(default=0, ge=0)
    updated_seconds: int = Field(ge=0)
    short_awarded: bool = False
    long_awarded: bool = False


def start(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = RestRequest.model_validate(proposal.parameters)
    if proposal.embodied_entity_id is None:
        raise ValueError("rest requires an embodied entity")
    key = str(proposal.embodied_entity_id)
    body = state.projections.get("tabletop.entities", {}).get(key)
    now = seconds(state)
    clock = state.projections["tabletop.clock"]["singleton"]
    if clock["run_id"] != str(proposal.run_id):
        raise ValueError("rest requires the current run's clock")
    if body is None or int(body.get("hp", 0)) <= 0 or incapacitated(body):
        raise ValueError("rest requires a capable living body")
    if wait_seconds(state, proposal.embodied_entity_id):
        raise ValueError("finish the current action before resting")
    if state.projections.get("tabletop.routines", {}).get(key, {}).get("enabled"):
        raise ValueError("disable the body routine before starting a manual rest")
    rows = state.projections.get(ACTIVITIES, {})
    if key in rows and rows[key]["status"] in {"RUNNING", "WAITING"}:
        raise ValueError("finish or cancel the existing activity first")
    if key not in rows and len(rows) >= 256:
        raise ValueError("activity body limit reached")
    activity = Activity(
        activity_id=uuid.uuid5(
            proposal.run_id, f"rest:{proposal.actor_id}:{proposal.idempotency_key}"
        ),
        entity_id=proposal.embodied_entity_id,
        kind="REST",
        details={"rest_kind": request.kind},
        duration_seconds=SHORT_SECONDS if request.kind == "SHORT" else LONG_SECONDS,
        started_seconds=now,
        updated_seconds=now,
        origin=position(state, key),
        cause="MANUAL",
    )
    return CommandResult(
        result=RestResult(
            activity_id=activity.activity_id,
            kind=request.kind,
            duration_seconds=activity.duration_seconds,
        ).model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection=ACTIVITIES,
                operation="SET",
                entity_id=activity.entity_id,
                values=activity.model_dump(mode="json"),
            ),
        ),
        domain_tags=("tabletop", "rest"),
    )


def configure_limits(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ResourceLimitsRequest.model_validate(proposal.parameters)
    body = state.projections.get("tabletop.entities", {}).get(str(request.entity_id))
    if body is None:
        raise ValueError("resource limits require an existing body")
    # Capacity changes do not heal, revive, spend or silently discard current resources.
    if request.max_hp < int(body.get("hp", 0)) or request.max_mana < int(body.get("mana", 0)):
        raise ValueError("resource limits cannot be lower than current resources")
    return CommandResult(
        result=request.model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.entity_id,
                values={"max_hp": request.max_hp, "max_mana": request.max_mana},
            ),
        ),
        domain_tags=("operator", "resource_configuration"),
    )


def recover(activity: Activity, body: dict, start: int, until: int, *, allowed: bool) -> Activity:
    """Mutate only the clock's private body and return the single canonical activity record."""
    if activity.kind not in {"REST", "SLEEP"}:
        return activity
    if until < start:
        raise ValueError("rest time cannot move backward")
    details = dict(activity.details)
    raw = details.get("recovery")
    row = RestProgress.model_validate(raw) if raw else RestProgress(updated_seconds=start)
    if not allowed or int(body.get("hp", 0)) <= 0 or incapacitated(body):
        details.pop("recovery", None)
        return activity.model_copy(update={"details": details})
    if row.updated_seconds != start:
        row = RestProgress(updated_seconds=start)
    previous_hp, previous_mana = int(body["hp"]), int(body.get("mana", 0))
    elapsed = row.elapsed_seconds + until - start
    updates = {"elapsed_seconds": elapsed, "updated_seconds": until}
    maximum = max(0, int(body.get("max_hp", 0)))
    if not row.short_awarded and elapsed >= SHORT_SECONDS:
        if maximum:
            body["hp"] = max(
                int(body["hp"]), min(maximum, int(body["hp"]) + max(1, (maximum + 3) // 4))
            )
        updates["short_awarded"] = True
    if not row.long_awarded and elapsed >= LONG_SECONDS:
        completed = start + max(0, LONG_SECONDS - row.elapsed_seconds)
        previous = body.get("last_long_rest_seconds")
        if previous is None or completed >= int(previous) + LONG_INTERVAL:
            if maximum:
                body["hp"] = max(int(body["hp"]), maximum)
            if "max_mana" in body:
                body["mana"] = max(int(body.get("mana", 0)), int(body["max_mana"]))
            body["last_long_rest_seconds"] = completed
        updates["long_awarded"] = True
    details["recovery"] = row.model_copy(update=updates).model_dump(mode="json")
    return activity.model_copy(update={"details": details}).account(
        ActivityOutputs(
            hp_restored=int(body["hp"]) - previous_hp,
            mana_restored=int(body.get("mana", 0)) - previous_mana,
        )
    )


def boundaries(state: BranchState, start: int, until: int) -> tuple[int, ...]:
    points = set()
    for raw in state.projections.get(ACTIVITIES, {}).values():
        activity = Activity.model_validate(raw)
        if activity.kind not in {"REST", "SLEEP"} or activity.status not in {"RUNNING", "WAITING"}:
            continue
        progress = activity.details.get("recovery", {})
        elapsed = int(progress.get("elapsed_seconds", 0))
        for threshold in (SHORT_SECONDS, LONG_SECONDS):
            if elapsed < threshold:
                points.add(start + threshold - elapsed)
        if activity.routine_id is None and activity.due_seconds is not None:
            points.add(activity.due_seconds)
    return tuple(sorted(point for point in points if start < point <= until))


def with_rest_interruptions(handler: CommandHandler) -> CommandHandler:
    def execute(proposal: CommandProposal, state: BranchState) -> CommandResult:
        result = handler(proposal, state)
        if not result.accepted:
            return result
        after = state.working_copy()
        for delta in result.deltas:
            after.apply(delta)
        interrupted: set[str] = set()
        if proposal.command_type not in UNTIMED_COMMANDS:
            interrupted.add(str(proposal.embodied_entity_id))
        for delta in result.deltas:
            if delta.projection == "tabletop.action_time" and delta.entity_id is not None:
                interrupted.add(str(delta.entity_id))
        for key, old in state.projections.get("tabletop.entities", {}).items():
            body = after.projections.get("tabletop.entities", {}).get(key, {})
            if int(body.get("hp", 0)) < int(old.get("hp", 0)):
                interrupted.add(key)
        deltas = []
        for key in sorted(interrupted):
            raw = after.projections.get(ACTIVITIES, {}).get(key)
            if not raw or raw["kind"] not in {"REST", "SLEEP"}:
                continue
            activity = Activity.model_validate(raw)
            details = dict(activity.details)
            details.pop("recovery", None)
            activity = activity.model_copy(update={"details": details})
            if activity.details.get("rest_kind") and activity.status in {"RUNNING", "WAITING"}:
                activity = activity.evolve(
                    status="CANCELLED", reason="DANGER", updated_seconds=seconds(after)
                )
            updated = activity.model_dump(mode="json")
            if updated != raw:
                deltas.append(
                    StateDelta(
                        projection=ACTIVITIES,
                        operation="SET",
                        entity_id=uuid.UUID(key),
                        values=updated,
                    )
                )
        return result.model_copy(update={"deltas": (*result.deltas, *deltas)})

    return execute


def command_definitions() -> tuple[CommandDefinition, ...]:
    return (
        CommandDefinition(
            command_type="tabletop.rest.start",
            version=REST_VERSION,
            required_capabilities=frozenset({"action.propose", "entity.act"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            requires_controlled_entity=True,
            handler=start,
            request_model=RestRequest,
            result_model=RestResult,
        ),
        CommandDefinition(
            command_type="tabletop.resources.configure",
            version=REST_VERSION,
            required_capabilities=frozenset({"action.propose", "entity.control"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=configure_limits,
            request_model=ResourceLimitsRequest,
            result_model=ResourceLimitsResult,
        ),
    )
