"""Typed deterministic world time over the existing atomic branch projection store."""

from __future__ import annotations

import uuid
from datetime import UTC, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domains.tabletop.activities import ACTIVITIES, SCHEDULE, WEATHER, advance_activities
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

CLOCK = "tabletop.clock"


class Clock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: uuid.UUID
    executor_actor_id: uuid.UUID
    seconds: int = Field(default=0, ge=0)
    epoch: int = Field(ge=1)
    step: int = Field(default=0, ge=0)
    paused: bool = True
    seconds_per_tick: int = Field(default=1, ge=1, le=3600)
    offline_policy: Literal["FREEZE", "CATCH_UP"] = "FREEZE"
    max_catch_up_ticks: int = Field(default=10, ge=1, le=60)
    until_seconds: int | None = Field(default=None, ge=0)
    next_due: AwareDatetime


class ConfigureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_epoch: int = Field(ge=0)
    executor_actor_id: uuid.UUID
    paused: bool = True
    seconds_per_tick: int = Field(default=1, ge=1, le=3600)
    offline_policy: Literal["FREEZE", "CATCH_UP"] = "FREEZE"
    max_catch_up_ticks: int = Field(default=10, ge=1, le=60)
    until_seconds: int | None = Field(default=None, ge=0)
    wall_time: AwareDatetime


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    epoch: int = Field(ge=1)
    step: int = Field(ge=0)
    wall_time: AwareDatetime


class AdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_epoch: int = Field(ge=1)
    expected_seconds: int = Field(ge=0)
    to_seconds: int = Field(ge=1)


class ClockResult(BaseModel):
    seconds: int = Field(ge=0)
    epoch: int = Field(ge=1)
    step: int = Field(default=0, ge=0)


def read_clock(state: BranchState) -> Clock | None:
    raw = state.projections.get(CLOCK, {}).get("singleton")
    return Clock.model_validate(raw) if raw else None


def configure(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ConfigureRequest.model_validate(proposal.parameters)
    old = read_clock(state)
    if request.expected_epoch != (old.epoch if old else 0):
        raise ValueError("clock epoch changed")
    seconds = old.seconds if old else 0
    if request.until_seconds is not None and request.until_seconds <= seconds:
        raise ValueError("clock boundary must be in the future")
    clock = Clock(
        **request.model_dump(exclude={"expected_epoch", "wall_time"}),
        run_id=proposal.run_id,
        seconds=seconds,
        epoch=request.expected_epoch + 1,
        next_due=request.wall_time.astimezone(UTC) + timedelta(seconds=1),
    )
    return CommandResult(
        result={"epoch": clock.epoch, "seconds": clock.seconds},
        deltas=(
            StateDelta(projection=CLOCK, operation="SET", values=clock.model_dump(mode="json")),
        ),
        domain_tags=("operator", "clock_configuration"),
    )


def advance_result(state: BranchState, clock: Clock, until: int, **updates) -> CommandResult:
    working = state.working_copy()
    advance_activities(working, until)
    updated = clock.model_copy(update={"seconds": until, "step": clock.step + 1, **updates})
    deltas = [StateDelta(projection=CLOCK, operation="SET", values=updated.model_dump(mode="json"))]
    for projection in (
        ACTIVITIES,
        WEATHER,
        SCHEDULE,
        "tabletop.entities",
        "tabletop.vitals",
        "tabletop.population",
        "tabletop.population_transitions",
        "tabletop.routines",
        "tabletop.obligations",
        "tabletop.spatial.positions",
    ):
        before, after = (
            state.projections.get(projection, {}),
            working.projections.get(projection, {}),
        )
        for key in sorted(before.keys() | after.keys()):
            identity = None if key == "singleton" else uuid.UUID(key)
            if key not in after:
                deltas.append(
                    StateDelta(projection=projection, operation="DELETE", entity_id=identity)
                )
            elif before.get(key) != after[key]:
                deltas.append(
                    StateDelta(
                        projection=projection,
                        operation="SET",
                        entity_id=identity,
                        values=after[key],
                    )
                )
    return CommandResult(
        result={"seconds": until, "epoch": updated.epoch, "step": updated.step},
        deltas=tuple(deltas),
        domain_tags=("operator", "world_time"),
    )


def tick(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = TickRequest.model_validate(proposal.parameters)
    clock = read_clock(state)
    if clock is None or clock.paused or clock.run_id != proposal.run_id:
        raise ValueError("clock is not running for this run")
    if (request.epoch, request.step, proposal.actor_id) != (
        clock.epoch,
        clock.step,
        clock.executor_actor_id,
    ):
        raise ValueError("clock owner or epoch/step changed")
    if request.wall_time < clock.next_due:
        raise ValueError("clock tick is not due")
    count = (
        1
        if clock.offline_policy == "FREEZE"
        else min(
            clock.max_catch_up_ticks, int((request.wall_time - clock.next_due).total_seconds()) + 1
        )
    )
    until = clock.seconds + count * clock.seconds_per_tick
    if clock.until_seconds is not None:
        until = min(until, clock.until_seconds)
    next_due = (
        request.wall_time.astimezone(UTC) if clock.offline_policy == "FREEZE" else clock.next_due
    ) + timedelta(seconds=count)
    return advance_result(
        state,
        clock,
        until,
        next_due=next_due,
        paused=clock.until_seconds is not None and until == clock.until_seconds,
    )


def advance_to(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = AdvanceRequest.model_validate(proposal.parameters)
    clock = read_clock(state)
    if clock is None or not clock.paused or clock.run_id != proposal.run_id:
        raise ValueError("manual advance requires this run's paused clock")
    if (request.expected_epoch, request.expected_seconds) != (clock.epoch, clock.seconds):
        raise ValueError("clock changed")
    if not clock.seconds < request.to_seconds <= clock.seconds + 86400:
        raise ValueError("advance must be forward and at most one simulated day")
    return advance_result(state, clock, request.to_seconds)


def command_definitions() -> tuple[CommandDefinition, ...]:
    return tuple(
        CommandDefinition(
            command_type=name,
            version="1.4.0" if name != "tabletop.clock.configure" else "1.0.0",
            required_capabilities=frozenset(
                {"action.propose", "entity.control"}
                if name != "tabletop.clock.tick"
                else {"action.propose", "world.read"}
            ),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=handler,
            request_model=model,
            result_model=ClockResult,
        )
        for name, handler, model in (
            ("tabletop.clock.configure", configure, ConfigureRequest),
            ("tabletop.clock.tick", tick, TickRequest),
            ("tabletop.clock.advance", advance_to, AdvanceRequest),
        )
    )
