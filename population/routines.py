"""Deterministic coarse activity scheduling, independent of viewers and connections."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.action_time import wait_seconds
from domains.tabletop.activities import (
    ACTIVITIES,
    WEATHER,
    Activity,
    ActivityOutputs,
    ActivityRecords,
    eat_meal,
    position,
    seconds,
)
from domains.tabletop.rules import incapacitated
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.state import BranchState
from population.life import LifePlan, validate_place
from population.models import PopulationLevel
from population.runtime import MEMBERS, projection_deltas, transition

ROUTINES = "tabletop.routines"
POLICY_VERSION = "npc-routines-1.6.0"


class RoutineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID
    expected_version: int = Field(ge=0)
    enabled: bool = True
    work_seconds: int = Field(default=1800, ge=60, le=86400)
    rest_seconds: int = Field(default=600, ge=60, le=86400)
    meal_seconds: int = Field(default=5, ge=5, le=3600)
    fatigue_limit: int = Field(default=3600, ge=60, le=86400)
    hunger_limit: int = Field(default=14400, ge=60, le=86400)
    relevance_radius: int = Field(default=12, ge=0, le=1000)
    relevance_anchors: tuple[uuid.UUID, ...] = Field(default=(), max_length=32)
    life: LifePlan | None = None


class RoutineResult(BaseModel):
    entity_id: uuid.UUID
    version: int


def configure(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = RoutineRequest.model_validate(proposal.parameters)
    key = str(request.entity_id)
    if not any(row["entity_id"] == key for row in state.projections.get(MEMBERS, {}).values()):
        raise ValueError("bind the population member to this body first")
    old = state.projections.get(ROUTINES, {}).get(key)
    if request.expected_version != (int(old["version"]) if old else 0):
        raise ValueError("routine version changed")
    if old is None and len(state.projections.get(ROUTINES, {})) >= 32:
        raise ValueError("routine body limit reached")
    if any(
        str(identity) not in state.projections.get("tabletop.entities", {})
        for identity in request.relevance_anchors
    ):
        raise ValueError("relevance anchors require existing bodies in this branch")
    activity = state.projections.get(ACTIVITIES, {}).get(key)
    if activity and activity["status"] in {"RUNNING", "WAITING"} and not activity.get("routine_id"):
        raise ValueError("cancel the manual activity before assigning a routine")
    now = seconds(state)
    if request.life is not None:
        validate_place(state, key, request.life.home)
        validate_place(state, key, request.life.workplace)
        if request.life.planning:
            for goal in request.life.planning.goals:
                validate_place(state, key, goal.place)
    working = state.working_copy()
    if request.life is not None or (old and old.get("life")):
        working.projections["tabletop.entities"][key]["asleep"] = False
    version = request.expected_version + 1
    row = {
        **request.model_dump(mode="json"),
        "version": version,
        "routine_id": str(uuid.uuid5(proposal.run_id, f"routine:{key}:{version}")),
        "policy_version": POLICY_VERSION,
        "phase_sequence": 0,
        "updated_seconds": now,
        "resume_work": None,
        "suspended": {},
    }
    working.projections.setdefault(ROUTINES, {})[key] = row
    if activity and activity.get("routine_id"):
        working.projections[ACTIVITIES][key] = (
            Activity.model_validate(activity)
            .evolve(status="CANCELLED", reason=None, updated_seconds=now)
            .model_dump(mode="json")
        )
    if request.enabled:
        new_phase(working, key, row, "WEED", now)
    return CommandResult(
        result={"entity_id": key, "version": version},
        deltas=projection_deltas(state, working, (ROUTINES, ACTIVITIES, "tabletop.entities")),
        domain_tags=("operator", "npc_routine_configuration"),
    )


def new_phase(
    state: BranchState, key: str, routine: dict, kind: Literal["WEED", "REST", "EAT"], now: int
) -> Activity:
    routine["phase_sequence"] += 1
    activity = Activity(
        activity_id=uuid.uuid5(
            uuid.UUID(routine["routine_id"]), f"phase:{routine['phase_sequence']}"
        ),
        entity_id=uuid.UUID(key),
        kind=kind,
        duration_seconds=routine[
            {"WEED": "work_seconds", "REST": "rest_seconds", "EAT": "meal_seconds"}[kind]
        ],
        started_seconds=now,
        updated_seconds=now,
        origin=position(state, key),
        routine_id=uuid.UUID(routine["routine_id"]),
    )
    state.projections.setdefault(ACTIVITIES, {})[key] = activity.model_dump(mode="json")
    return activity


def food(body: dict) -> int:
    return max(0, int(body.get("inventory", {}).get("food", 0)))


def advance_body(
    state: BranchState, key: str, routine: dict, until: int, records: ActivityRecords
) -> None:
    from domains.tabletop.rest import recover

    body = state.projections.get("tabletop.entities", {}).get(key)
    cursor = int(routine["updated_seconds"])
    if until < cursor:
        raise ValueError("routine time cannot move backward")
    busy = bool(wait_seconds(state, uuid.UUID(key), at_seconds=cursor))
    unavailable = body is None or int(body.get("hp", 0)) <= 0 or incapacitated(body)
    if body is None or unavailable or busy:
        activity = Activity.model_validate(state.projections[ACTIVITIES][key])
        if activity.status != "COMPLETED":
            if body is not None:
                activity = recover(activity, body, cursor, until, allowed=False)
            updated = activity.evolve(
                status="WAITING",
                reason="INCAPACITATED" if unavailable else "ACTION_BUSY",
                updated_seconds=until,
            )
            state.projections[ACTIVITIES][key] = updated.model_dump(mode="json")
            if updated.activity_id in records:
                records[updated.activity_id] = updated
        if body is not None and int(body.get("hp", 0)) > 0:
            body["hunger"] = int(body.get("hunger", 0)) + until - cursor
        routine["updated_seconds"] = until
        return
    while True:
        activity = Activity.model_validate(state.projections[ACTIVITIES][key])
        hunger, fatigue = int(body.get("hunger", 0)), int(body.get("fatigue", 0))
        if activity.status == "COMPLETED":
            if activity.kind != "WEED" and routine["resume_work"] is not None:
                resumed = Activity.model_validate(routine["resume_work"]).evolve(
                    updated_seconds=cursor, status="RUNNING", reason=None
                )
                state.projections[ACTIVITIES][key] = resumed.model_dump(mode="json")
                routine["resume_work"] = None
                activity = resumed
            else:
                activity = new_phase(
                    state, key, routine, "REST" if activity.kind == "WEED" else "WEED", cursor
                )
        if activity.kind != "EAT" and hunger >= routine["hunger_limit"]:
            if activity.kind == "WEED":
                routine["resume_work"] = activity.model_dump(mode="json")
            activity = new_phase(state, key, routine, "EAT", cursor)
        elif activity.kind == "WEED" and fatigue >= routine["fatigue_limit"]:
            routine["resume_work"] = activity.model_dump(mode="json")
            activity = new_phase(state, key, routine, "REST", cursor)
        reason = (
            "MOVED"
            if position(state, key) != activity.origin
            else "RAIN"
            if activity.kind == "WEED"
            and state.projections.get(WEATHER, {})
            .get("singleton", {})
            .get(activity.origin["zone_id"], False)
            else "NO_FOOD"
            if activity.kind == "EAT" and food(body) == 0
            else None
        )
        if cursor == until or reason:
            activity = recover(activity, body, cursor, cursor, allowed=reason is None)
            stop = until
            if reason and activity.kind != "EAT" and hunger < routine["hunger_limit"]:
                stop = min(until, cursor + routine["hunger_limit"] - hunger)
            body["hunger"] = hunger + stop - cursor
            updated = activity.evolve(
                status="WAITING" if reason else "RUNNING",
                reason=reason,
                updated_seconds=stop,
            )
            state.projections[ACTIVITIES][key] = updated.model_dump(mode="json")
            if updated.activity_id in records:
                records[updated.activity_id] = updated
            if stop != cursor:
                cursor = stop
                # Re-evaluate needs even at an exact end boundary, matching split ticks.
                continue
            break
        if activity.due_seconds is None:
            activity = activity.evolve(status="RUNNING", reason=None, updated_seconds=cursor)
        assert activity.due_seconds is not None
        duration = min(until, activity.due_seconds) - cursor
        if activity.kind != "EAT" and hunger < routine["hunger_limit"]:
            duration = min(duration, routine["hunger_limit"] - hunger)
        if activity.kind == "WEED" and fatigue < routine["fatigue_limit"]:
            duration = min(duration, routine["fatigue_limit"] - fatigue)
        body["hunger"] = hunger + duration
        if activity.kind == "WEED":
            body["weeded_units"] = int(body.get("weeded_units", 0)) + duration
            body["fatigue"] = fatigue + duration
            activity = activity.account(ActivityOutputs(weeded_units=duration))
        elif activity.kind == "REST":
            body["fatigue"] = max(0, fatigue - duration)
            activity = activity.account(ActivityOutputs(fatigue_relieved=fatigue - body["fatigue"]))
        activity = recover(activity, body, cursor, cursor + duration, allowed=True)
        cursor += duration
        total = activity.progress_seconds + duration
        complete = total == activity.duration_seconds
        if complete and activity.kind == "EAT":
            activity = eat_meal(activity, body)
        updated = activity.evolve(
            progress_seconds=total,
            updated_seconds=cursor,
            status="COMPLETED" if complete else "RUNNING",
            reason=None,
        )
        state.projections[ACTIVITIES][key] = updated.model_dump(mode="json")
        records[updated.activity_id] = updated
    routine["updated_seconds"] = until


def advance_routines(
    state: BranchState, until: int, records: ActivityRecords, start: int | None = None
) -> None:
    if state.projections.get("tabletop.obligations") or any(
        row["enabled"] and row.get("life") for row in state.projections.get(ROUTINES, {}).values()
    ):
        from population.life import advance_life

        advance_life(state, until, records, start)
        return
    for key, routine in sorted(state.projections.get(ROUTINES, {}).items()):
        if routine["enabled"]:
            advance_body(state, key, routine, until, records)


def routine_relevance(state: BranchState, member: dict, routine: dict) -> PopulationLevel:
    """Resolve interaction relevance from current positions and manager overrides."""
    if member["relevance"] != "AUTO":
        return PopulationLevel(member["relevance"])
    bodies = state.projections.get("tabletop.entities", {})
    sensory = state.projections.get("tabletop.sensory_profiles", {})
    key = member["entity_id"]
    if int(bodies.get(key, {}).get("hp", 0)) <= 0:
        return PopulationLevel.MATERIALIZED
    anchors = routine["relevance_anchors"] or sorted(
        identity for identity, row in sensory.items() if row.get("controller_actor_id")
    )
    origin = position(state, key)
    for identity in anchors:
        if identity == key or int(bodies.get(identity, {}).get("hp", 0)) <= 0:
            continue
        anchor = position(state, identity)
        if (
            anchor["zone_id"] == origin["zone_id"]
            and sum((anchor[axis] - origin[axis]) ** 2 for axis in ("x", "y", "z"))
            <= routine["relevance_radius"] ** 2
        ):
            return PopulationLevel.ACTIVE
    return PopulationLevel.MATERIALIZED


def uses_offscreen_routine(state: BranchState, entity_id: uuid.UUID) -> bool:
    key = str(entity_id)
    body = state.projections.get("tabletop.entities", {}).get(key, {})
    routine = state.projections.get(ROUTINES, {}).get(key)
    if body.get("entity_type") != "NPC" or not routine or not routine["enabled"]:
        return False
    return any(
        member["entity_id"] == key
        and routine_relevance(state, member, routine) is PopulationLevel.MATERIALIZED
        for member in state.projections.get(MEMBERS, {}).values()
    )


def reconcile_relevance(state: BranchState, now: int) -> None:
    """Record the lifecycle at the same physical instant that determines action eligibility."""
    for persona, member in sorted(state.projections.get(MEMBERS, {}).items()):
        routine = state.projections.get(ROUTINES, {}).get(member["entity_id"])
        if routine is not None:
            transition(
                state,
                uuid.UUID(persona),
                routine_relevance(state, member, routine),
                now,
                "physical_relevance",
            )


def command_definitions() -> tuple[CommandDefinition, ...]:
    return (
        CommandDefinition(
            "tabletop.routine.configure",
            frozenset({"action.propose", "entity.control"}),
            frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            configure,
            request_model=RoutineRequest,
            result_model=RoutineResult,
        ),
    )
