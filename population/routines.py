"""Deterministic coarse activity scheduling, independent of viewers and connections."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.activities import ACTIVITIES, WEATHER, Activity, position, seconds
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.state import BranchState
from population.life import LifePlan, validate_place
from population.models import PopulationLevel
from population.runtime import MEMBERS, projection_deltas, transition

ROUTINES = "tabletop.routines"
POLICY_VERSION = "npc-routines-1.2.0"


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
        working.projections[ACTIVITIES][key] = {**activity, "status": "CANCELLED", "reason": None}
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


def advance_body(state: BranchState, key: str, routine: dict, until: int) -> None:
    body = state.projections.get("tabletop.entities", {}).get(key)
    cursor = int(routine["updated_seconds"])
    if until < cursor:
        raise ValueError("routine time cannot move backward")
    if body is None or int(body.get("hp", 0)) <= 0:
        raw = state.projections[ACTIVITIES][key]
        raw.update(status="WAITING", reason="INCAPACITATED", updated_seconds=until)
        routine["updated_seconds"] = until
        return
    while True:
        activity = Activity.model_validate(state.projections[ACTIVITIES][key])
        hunger, fatigue = int(body.get("hunger", 0)), int(body.get("fatigue", 0))
        if activity.status == "COMPLETED":
            if activity.kind == "EAT":
                # Food is charged at this boundary, once, before choosing the next phase.
                inventory = dict(body.get("inventory", {}))
                inventory["food"] = food(body) - 1
                body["inventory"] = inventory
                body["hunger"] = max(0, hunger - 14400)
                body["meals_eaten"] = int(body.get("meals_eaten", 0)) + 1
                hunger = int(body["hunger"])
            if activity.kind != "WEED" and routine["resume_work"] is not None:
                resumed = Activity.model_validate(routine["resume_work"]).model_copy(
                    update={"updated_seconds": cursor, "status": "RUNNING", "reason": None}
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
            stop = until
            if reason and activity.kind != "EAT" and hunger < routine["hunger_limit"]:
                stop = min(until, cursor + routine["hunger_limit"] - hunger)
            body["hunger"] = hunger + stop - cursor
            state.projections[ACTIVITIES][key] = activity.model_copy(
                update={
                    "status": "WAITING" if reason else "RUNNING",
                    "reason": reason,
                    "updated_seconds": stop,
                }
            ).model_dump(mode="json")
            if stop != cursor:
                cursor = stop
                # Re-evaluate needs even at an exact end boundary, matching split ticks.
                continue
            break
        duration = min(until - cursor, activity.duration_seconds - activity.progress_seconds)
        if activity.kind != "EAT" and hunger < routine["hunger_limit"]:
            duration = min(duration, routine["hunger_limit"] - hunger)
        if activity.kind == "WEED" and fatigue < routine["fatigue_limit"]:
            duration = min(duration, routine["fatigue_limit"] - fatigue)
        body["hunger"] = hunger + duration
        if activity.kind == "WEED":
            body["weeded_units"] = int(body.get("weeded_units", 0)) + duration
            body["fatigue"] = fatigue + duration
        elif activity.kind == "REST":
            body["fatigue"] = max(0, fatigue - duration)
        cursor += duration
        total = activity.progress_seconds + duration
        state.projections[ACTIVITIES][key] = activity.model_copy(
            update={
                "progress_seconds": total,
                "updated_seconds": cursor,
                "status": "COMPLETED" if total == activity.duration_seconds else "RUNNING",
                "reason": None,
            }
        ).model_dump(mode="json")
    routine["updated_seconds"] = until


def advance_routines(state: BranchState, until: int, start: int | None = None) -> None:
    if state.projections.get("tabletop.obligations") or any(
        row["enabled"] and row.get("life") for row in state.projections.get(ROUTINES, {}).values()
    ):
        from population.life import advance_life

        advance_life(state, until, start)
        return
    for key, routine in sorted(state.projections.get(ROUTINES, {}).items()):
        if routine["enabled"]:
            advance_body(state, key, routine, until)


def reconcile_relevance(state: BranchState, now: int) -> None:
    """Physical commands change state at the current simulated instant, before elapsed work."""
    # Relevance is physical proximity, never a browser, camera, or human login.
    bodies = state.projections.get("tabletop.entities", {})
    sensory = state.projections.get("tabletop.sensory_profiles", {})
    for persona, member in sorted(state.projections.get(MEMBERS, {}).items()):
        key = member["entity_id"]
        routine = state.projections.get(ROUTINES, {}).get(key)
        if routine is None:
            continue
        anchors = routine["relevance_anchors"] or sorted(
            identity for identity, row in sensory.items() if row.get("controller_actor_id")
        )
        origin = position(state, key)
        nearby = any(
            identity != key
            and identity in bodies
            and int(bodies[identity].get("hp", 0)) > 0
            and position(state, identity)["zone_id"] == origin["zone_id"]
            and sum(
                (position(state, identity)[axis] - origin[axis]) ** 2 for axis in ("x", "y", "z")
            )
            <= routine["relevance_radius"] ** 2
            for identity in anchors
        )
        level = member["relevance"]
        if level == "AUTO":
            level = (
                "ACTIVE" if nearby and int(bodies.get(key, {}).get("hp", 0)) > 0 else "MATERIALIZED"
            )
        transition(state, uuid.UUID(persona), PopulationLevel(level), now, "physical_relevance")


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
