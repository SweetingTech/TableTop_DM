"""Bounded physical schedules: commuting, daily sleep, and joint social attendance."""

from __future__ import annotations

import heapq
import math
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
from domains.tabletop.spatial import MoveRequest, move_entity
from kernel.command_bus import CommandDefinition, CommandHandler
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.errors import BodyIncapacitated, BodySleeping
from kernel.state import BranchState
from population.runtime import projection_deltas

OBLIGATIONS = "tabletop.obligations"
DAY = 86400


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: int = Field(ge=-100000, le=100000)
    y: int = Field(ge=-100000, le=100000)
    z: int = 0
    zone_id: str = Field(default="world", min_length=1, max_length=120)


class DailyGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    goal_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    kind: Literal["WEED", "REST"]
    place: Place
    seconds_per_day: int = Field(default=1800, ge=1, le=86400)
    priority: int = Field(default=50, ge=1, le=100)
    motive: Literal["DUTY", "CURIOSITY", "CARE", "RECOVERY"] | None = None


class DailyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    goals: tuple[DailyGoal, ...] = Field(min_length=1, max_length=8)
    retry_seconds: int = Field(default=300, ge=10, le=3600)
    motivated: bool = False

    @model_validator(mode="after")
    def unique_goals(self):
        if len({goal.goal_id for goal in self.goals}) != len(self.goals):
            raise ValueError("daily goal identifiers must be unique")
        return self


class LifePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    home: Place
    workplace: Place
    step_seconds: int = Field(default=60, ge=1, le=300)
    sleep_start_seconds: int = Field(default=79200, ge=0, lt=DAY)
    sleep_seconds: int = Field(default=28800, ge=60, lt=DAY)
    danger_quiet_seconds: int = Field(default=300, ge=1, le=3600)
    planning: DailyPlan | None = None


class ObligationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participants: tuple[uuid.UUID, ...] = Field(min_length=2, max_length=8)
    place: Place
    starts_seconds: int = Field(ge=0)
    duration_seconds: int = Field(default=300, ge=1, le=86400)
    grace_seconds: int = Field(default=300, ge=0, le=86400)
    lead_seconds: int = Field(default=300, ge=0, le=86400)
    repeat_seconds: int | None = Field(default=None, ge=600, le=604800)
    wake_for_obligation: bool = False
    radius: int = Field(default=1, ge=0, le=12)

    @model_validator(mode="after")
    def validate_schedule(self):
        if len(set(self.participants)) != len(self.participants):
            raise ValueError("obligation participants must be unique")
        if self.repeat_seconds is not None and self.repeat_seconds <= (
            self.lead_seconds + self.duration_seconds + self.grace_seconds
        ):
            raise ValueError("repeating obligation windows must not overlap")
        return self


class CancelObligation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    obligation_id: uuid.UUID
    expected_occurrence: int = Field(ge=0)


class ObligationResult(BaseModel):
    obligation_id: uuid.UUID


def validate_place(state: BranchState, key: str, place: Place) -> None:
    actual = position(state, key)
    if (place.zone_id, place.z) != (actual["zone_id"], actual["z"]):
        raise ValueError("local travel requires the body's current zone and elevation")
    blocked = {
        (int(row["x"]), int(row["y"]))
        for row in state.projections.get("tabletop.obstacles", {}).values()
    }
    if (place.x, place.y) in blocked:
        raise ValueError("travel destination is blocked")


def overlapping(first: dict, second: dict) -> bool:
    def window(row):
        return (
            row["starts_seconds"] - row["lead_seconds"],
            row["lead_seconds"] + row["grace_seconds"] + row["duration_seconds"],
        )

    a, width_a = window(first)
    b, width_b = window(second)
    period_a, period_b = first.get("repeat_seconds"), second.get("repeat_seconds")
    if period_a and period_b:
        cycle = math.gcd(period_a, period_b)
        distance = (b - a) % cycle
        return distance < width_a or cycle - distance < width_b
    if period_a or period_b:
        if period_b:
            a, b, width_a, width_b, period_a = b, a, width_b, width_a, period_b
        occurrence = max(0, (b - a) // period_a)
        return any(
            a + n * period_a < b + width_b and b < a + n * period_a + width_a
            for n in (occurrence - 1, occurrence, occurrence + 1)
            if n >= 0
        )
    return a < b + width_b and b < a + width_a


def schedule(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ObligationRequest.model_validate(proposal.parameters)
    now = seconds(state)
    if not now <= request.starts_seconds <= now + 604800:
        raise ValueError("obligation must start within the next seven simulated days")
    rows = state.projections.get(OBLIGATIONS, {})
    if len(rows) >= 128:
        raise ValueError("obligation record limit reached")
    for participant in request.participants:
        key = str(participant)
        validate_place(state, key, request.place)
        for row in rows.values():
            if (
                key not in row["participants"]
                or row["status"] == "CANCELLED"
                or (row["status"] in {"COMPLETED", "MISSED"} and row.get("repeat_seconds") is None)
            ):
                continue
            if overlapping(request.model_dump(), row):
                raise ValueError("participant already has an overlapping commitment")
    identity = uuid.uuid5(
        proposal.run_id, f"obligation:{proposal.actor_id}:{proposal.idempotency_key}"
    )
    working = state.working_copy()
    working.projections.setdefault(OBLIGATIONS, {})[str(identity)] = {
        **request.model_dump(mode="json"),
        "status": "PENDING",
        "occurrence": 0,
        "progress_seconds": 0,
        "completed_count": 0,
        "missed_count": 0,
        "started_seconds": None,
        "last_outcome": None,
    }
    return CommandResult(
        result={"obligation_id": str(identity)},
        deltas=projection_deltas(state, working, (OBLIGATIONS,)),
        domain_tags=("operator", "social_obligation"),
    )


def cancel(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = CancelObligation.model_validate(proposal.parameters)
    working = state.working_copy()
    row = working.projections.get(OBLIGATIONS, {}).get(str(request.obligation_id))
    if row is None or row["occurrence"] != request.expected_occurrence:
        raise ValueError("obligation occurrence changed")
    row["status"] = "CANCELLED"
    return CommandResult(
        result={"obligation_id": str(request.obligation_id)},
        deltas=projection_deltas(state, working, (OBLIGATIONS,)),
        domain_tags=("operator", "social_obligation"),
    )


def route(state: BranchState, key: str, destination: dict) -> list[dict]:
    """Stable bounded A*: same cardinal step/collision rules as manual movement."""
    start = position(state, key)
    if (start["zone_id"], start["z"]) != (destination["zone_id"], destination["z"]):
        return []
    source, goal = (start["x"], start["y"]), (destination["x"], destination["y"])
    if source == goal or sum(abs(source[i] - goal[i]) for i in (0, 1)) > 256:
        return []
    blocked = {
        (int(row["x"]), int(row["y"]))
        for row in state.projections.get("tabletop.obstacles", {}).values()
    }
    frontier = [(0, 0, source)]
    parents: dict[tuple[int, int], tuple[int, int] | None] = {source: None}
    costs = {source: 0}
    while frontier and len(parents) <= 4096:
        _, cost, point = heapq.heappop(frontier)
        if cost != costs[point]:
            continue
        if point == goal:
            path = []
            while point != source:
                path.append({**destination, "x": point[0], "y": point[1]})
                parent = parents[point]
                assert parent is not None
                point = parent
            return list(reversed(path))
        if cost >= 256:
            continue
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            adjacent = point[0] + dx, point[1] + dy
            if adjacent in blocked or cost + 1 >= costs.get(adjacent, 1000000):
                continue
            costs[adjacent], parents[adjacent] = cost + 1, point
            estimate = abs(adjacent[0] - goal[0]) + abs(adjacent[1] - goal[1])
            heapq.heappush(frontier, (cost + 1 + estimate, cost + 1, adjacent))
    return []


def sleeping(plan: dict, now: int) -> bool:
    return (now - plan["sleep_start_seconds"]) % DAY < plan["sleep_seconds"]


def wake_after_action(
    proposal: CommandProposal, state: BranchState, handler: CommandHandler
) -> CommandResult:
    """A human can wake by acting; captured autonomous proposals must wait for wakeup."""
    key = str(proposal.embodied_entity_id)
    body = state.projections.get("tabletop.entities", {}).get(key)
    if body is None:
        raise ValueError("a capable body is required for a voluntary action")
    if incapacitated(body):
        raise BodyIncapacitated("a capable body is required for a voluntary action")
    asleep = bool(body.get("asleep"))
    if asleep and proposal.decision_authorship == "CHARACTER_POLICY":
        raise BodySleeping("body is sleeping")
    evaluation = state
    if asleep:
        # Wake only in the isolated evaluation view. Failed actions leave the
        # original state asleep; successful actions append the canonical wake delta.
        evaluation = state.working_copy()
        evaluation.projections["tabletop.entities"][key]["asleep"] = False
    result = handler(proposal, evaluation)
    if not result.accepted:
        return result
    from kernel.contracts import StateDelta

    wake = {key} if asleep else set()
    for delta in result.deltas:
        old = state.projections.get("tabletop.entities", {}).get(str(delta.entity_id), {})
        if (
            delta.projection != "tabletop.entities"
            or not old.get("asleep")
            or "hp" not in delta.values
        ):
            continue
        hp = delta.values["hp"] + (int(old.get("hp", 0)) if delta.operation == "INCREMENT" else 0)
        if hp < int(old.get("hp", 0)):
            wake.add(str(delta.entity_id))
    deltas = tuple(
        StateDelta(
            projection="tabletop.entities",
            operation="MERGE",
            entity_id=uuid.UUID(identity),
            values={"asleep": False},
        )
        for identity in sorted(wake)
    )
    return result.model_copy(update={"deltas": (*result.deltas, *deltas)})


def switch(
    state: BranchState,
    key: str,
    row: dict,
    task: str,
    kind: str,
    now: int,
    duration: int,
    details: dict | None = None,
) -> Activity:
    old = Activity.model_validate(state.projections[ACTIVITIES][key])
    if old.task_key == task and old.status != "COMPLETED":
        return old
    cache = row.setdefault("suspended", {})
    if old.task_key and old.status != "COMPLETED" and old.kind not in {"SLEEP", "SOCIAL"}:
        cache[old.task_key] = old.model_dump(mode="json")
    raw = cache.pop(task, None)
    if (
        raw is not None
        and kind == "TRAVEL"
        and raw["details"].get("expected") != position(state, key)
    ):
        raw = None
    if raw is not None:
        activity = Activity.model_validate(raw).evolve(
            updated_seconds=now,
            origin=position(state, key) if kind == "EAT" else raw["origin"],
            status="RUNNING",
            reason=None,
        )
    else:
        row["phase_sequence"] += 1
        activity = Activity.model_validate(
            {
                "activity_id": str(
                    uuid.uuid5(uuid.UUID(row["routine_id"]), f"phase:{row['phase_sequence']}")
                ),
                "entity_id": key,
                "routine_id": row["routine_id"],
                "task_key": task,
                "kind": kind,
                "duration_seconds": max(1, duration),
                "started_seconds": now,
                "updated_seconds": now,
                "origin": position(state, key),
                "details": details or {},
            }
        )
    state.projections[ACTIVITIES][key] = activity.model_dump(mode="json")
    return activity


def travel(state: BranchState, key: str, row: dict, task: str, goal: dict, now: int) -> Activity:
    old = Activity.model_validate(state.projections[ACTIVITIES][key])
    if old.task_key == "travel:" + task and old.status != "COMPLETED":
        return old
    actual = position(state, key)
    path = route(state, key, goal)
    activity = switch(
        state,
        key,
        row,
        "travel:" + task,
        "TRAVEL",
        now,
        len(path) * row["life"]["step_seconds"],
        {"goal": goal, "path": path, "index": 0, "expected": actual, "step_progress": 0},
    )
    return activity


def finish_obligations(state: BranchState, now: int) -> None:
    for _, row in sorted(state.projections.get(OBLIGATIONS, {}).items()):
        if row["status"] == "CANCELLED":
            continue
        if row["status"] not in {"COMPLETED", "MISSED"}:
            complete = row["progress_seconds"] >= row["duration_seconds"]
            late = (
                row["started_seconds"] is None
                and now > row["starts_seconds"] + row["grace_seconds"]
            )
            expired = now >= row["starts_seconds"] + row["grace_seconds"] + row["duration_seconds"]
            if complete or late or expired:
                row["status"] = "COMPLETED" if complete else "MISSED"
                row["completed_count" if complete else "missed_count"] += 1
                row["last_outcome"] = {
                    "status": row["status"],
                    "at_seconds": now,
                    "occurrence": row["occurrence"],
                }
        if row["status"] in {"COMPLETED", "MISSED"} and row["repeat_seconds"] is not None:
            next_start = row["starts_seconds"] + row["repeat_seconds"]
            if now >= next_start - row["lead_seconds"]:
                row.update(
                    starts_seconds=next_start,
                    occurrence=row["occurrence"] + 1,
                    status="PENDING",
                    progress_seconds=0,
                    started_seconds=None,
                )


def due_obligation(state: BranchState, key: str, now: int) -> tuple[str, dict] | None:
    candidates = [
        (identity, row)
        for identity, row in state.projections.get(OBLIGATIONS, {}).items()
        if key in row["participants"]
        and row["status"] not in {"CANCELLED", "COMPLETED", "MISSED"}
        and now >= row["starts_seconds"] - row["lead_seconds"]
    ]
    return (
        min(candidates, key=lambda pair: (pair[1]["starts_seconds"], pair[0]))
        if candidates
        else None
    )


def prepare(state: BranchState, key: str, row: dict, now: int) -> None:
    body = state.projections["tabletop.entities"][key]
    old = Activity.model_validate(state.projections[ACTIVITIES][key])
    hp = int(body.get("hp", 0))
    if hp < row.get("checked_hp", hp) or (row.get("was_asleep") and not body.get("asleep")):
        row["awake_until"] = now + row["life"]["danger_quiet_seconds"]
    row["checked_hp"] = hp
    # Drop obsolete appointment caches; work and in-flight needs retain actual progress.
    valid = {
        f"travel:social:{identity}:{item['occurrence']}"
        for identity, item in state.projections.get(OBLIGATIONS, {}).items()
        if key in item["participants"]
        and item["status"] not in {"COMPLETED", "MISSED", "CANCELLED"}
    }
    row["suspended"] = {
        task: value
        for task, value in row.get("suspended", {}).items()
        if not task.startswith("travel:social:") or task in valid
    }
    if row["life"].get("planning"):
        from population.planning import prepare_plan

        prepare_plan(state, key, row, now)
        return
    reason = (
        "INCAPACITATED"
        if hp <= 0 or incapacitated(body)
        else "ACTION_BUSY"
        if wait_seconds(state, uuid.UUID(key), at_seconds=now)
        else "DANGER"
        if now < row.get("awake_until", 0)
        else "MOVED"
        if position(state, key)
        != (old.details.get("expected") if old.kind == "TRAVEL" else old.origin)
        and old.status != "COMPLETED"
        else None
    )
    if reason:
        if reason in {"DANGER", "MOVED"} or hp <= 0:
            body["asleep"] = False
            row["was_asleep"] = False
        if old.status != "COMPLETED":
            state.projections[ACTIVITIES][key] = old.evolve(
                updated_seconds=now, status="WAITING", reason=reason
            ).model_dump(mode="json")
        return
    plan, actual = row["life"], position(state, key)
    due = due_obligation(state, key, now)
    night = sleeping(plan, now) and not (due and due[1]["wake_for_obligation"])
    if night:
        if actual != plan["home"]:
            activity = travel(state, key, row, "home", plan["home"], now)
        else:
            remaining = plan["sleep_seconds"] - (now - plan["sleep_start_seconds"]) % DAY
            activity = switch(
                state,
                key,
                row,
                f"sleep:{(now - plan['sleep_start_seconds']) // DAY}",
                "SLEEP",
                now,
                remaining,
            )
    elif int(body.get("hunger", 0)) >= row["hunger_limit"]:
        activity = switch(state, key, row, "meal", "EAT", now, row["meal_seconds"])
    elif due:
        identity, obligation = due
        task = f"social:{identity}:{obligation['occurrence']}"
        if actual != obligation["place"]:
            activity = travel(state, key, row, task, obligation["place"], now)
        else:
            activity = switch(
                state,
                key,
                row,
                task,
                "SOCIAL",
                now,
                obligation["duration_seconds"],
                {"obligation_id": identity},
            )
    elif actual != plan["workplace"]:
        activity = travel(state, key, row, "work", plan["workplace"], now)
    elif (
        int(body.get("fatigue", 0)) >= row["fatigue_limit"]
        or (old.kind == "REST" and old.status != "COMPLETED")
        or (old.kind == "WEED" and old.status == "COMPLETED")
    ):
        activity = switch(state, key, row, "rest", "REST", now, row["rest_seconds"])
    else:
        activity = switch(state, key, row, "work", "WEED", now, row["work_seconds"])
    reason = None
    if activity.kind == "TRAVEL":
        details = dict(activity.details)
        path, index = details["path"], details["index"]
        blocked = {
            (int(item["x"]), int(item["y"]))
            for item in state.projections.get("tabletop.obstacles", {}).values()
        }
        if not path or (index < len(path) and (path[index]["x"], path[index]["y"]) in blocked):
            replacement = route(state, key, details["goal"])
            if replacement:
                details.update(path=replacement, index=0, step_progress=0)
                activity = activity.model_copy(
                    update={
                        "progress_seconds": 0,
                        "duration_seconds": len(replacement) * plan["step_seconds"],
                        "details": details,
                    }
                )
            else:
                reason = "PATH_BLOCKED"
    elif activity.kind == "WEED" and state.projections.get(WEATHER, {}).get("singleton", {}).get(
        actual["zone_id"], False
    ):
        reason = "RAIN"
    elif activity.kind == "EAT" and int(body.get("inventory", {}).get("food", 0)) <= 0:
        reason = "NO_FOOD"
    body["asleep"] = activity.kind == "SLEEP"
    row["was_asleep"] = body["asleep"]
    state.projections[ACTIVITIES][key] = activity.evolve(
        updated_seconds=now,
        status="WAITING" if reason else "RUNNING",
        reason=reason,
    ).model_dump(mode="json")


def ready(state: BranchState, identity: str, row: dict, now: int) -> bool:
    if now < row["starts_seconds"]:
        return False
    routines = state.projections.get("tabletop.routines", {})
    for key in row["participants"]:
        body = state.projections["tabletop.entities"].get(key, {})
        actual, place = position(state, key), row["place"]
        if (
            int(body.get("hp", 0)) <= 0
            or incapacitated(body)
            or wait_seconds(state, uuid.UUID(key), at_seconds=now)
            or body.get("asleep")
            or (actual["zone_id"], actual["z"]) != (place["zone_id"], place["z"])
            or sum((actual[axis] - place[axis]) ** 2 for axis in ("x", "y")) > row["radius"] ** 2
        ):
            return False
        if routines.get(key, {}).get("enabled") and routines[key].get("life"):
            activity = state.projections.get(ACTIVITIES, {}).get(key, {})
            if (
                activity.get("kind"),
                activity.get("details", {}).get("obligation_id"),
                activity.get("reason"),
            ) != ("SOCIAL", identity, None):
                return False
    return True


def command_definitions() -> tuple[CommandDefinition, ...]:
    return tuple(
        CommandDefinition(
            name,
            frozenset({"action.propose", "entity.control"}),
            frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler,
            request_model=model,
            result_model=ObligationResult,
        )
        for name, handler, model in (
            ("tabletop.obligation.schedule", schedule, ObligationRequest),
            ("tabletop.obligation.cancel", cancel, CancelObligation),
        )
    )


def next_boundary(state: BranchState, now: int, until: int) -> int:
    candidates = [until]
    for row in state.projections.get(OBLIGATIONS, {}).values():
        if row["status"] == "CANCELLED":
            continue
        start = row["starts_seconds"]
        if row["status"] in {"COMPLETED", "MISSED"}:
            if row["repeat_seconds"] is not None:
                candidates.append(start + row["repeat_seconds"] - row["lead_seconds"])
            continue
        candidates.extend(
            (
                start - row["lead_seconds"],
                start,
                start + row["grace_seconds"] + 1,
                start + row["grace_seconds"] + row["duration_seconds"],
            )
        )
        if row["status"] == "ATTENDING":
            candidates.append(now + row["duration_seconds"] - row["progress_seconds"])
    for key, row in state.projections.get("tabletop.routines", {}).items():
        if not row["enabled"] or not row.get("life"):
            continue
        plan = row["life"]
        if plan.get("planning"):
            interval = plan["planning"]["retry_seconds"]
            candidates.extend((now + (interval - now % interval), now + (DAY - now % DAY)))
        for offset in (
            plan["sleep_start_seconds"],
            (plan["sleep_start_seconds"] + plan["sleep_seconds"]) % DAY,
        ):
            candidates.append(now + ((offset - now % DAY) % DAY or DAY))
        candidates.append(row.get("awake_until", 0))
        body = state.projections["tabletop.entities"][key]
        if int(body.get("hp", 0)) <= 0:
            continue
        activity = Activity.model_validate(state.projections[ACTIVITIES][key])
        if activity.kind != "SLEEP" and int(body.get("hunger", 0)) < row["hunger_limit"]:
            candidates.append(now + row["hunger_limit"] - int(body.get("hunger", 0)))
        if activity.status != "RUNNING":
            continue
        if activity.kind == "TRAVEL":
            candidates.append(now + plan["step_seconds"] - activity.details["step_progress"])
        if activity.due_seconds is not None:
            candidates.append(activity.due_seconds)
        if (
            activity.kind == "WEED" or (plan.get("planning") and activity.kind == "TRAVEL")
        ) and int(body.get("fatigue", 0)) < row["fatigue_limit"]:
            candidates.append(now + row["fatigue_limit"] - int(body.get("fatigue", 0)))
    return min(value for value in candidates if value > now)


def progress_body(
    state: BranchState, key: str, row: dict, until: int, records: ActivityRecords
) -> None:
    from domains.tabletop.rest import recover

    body = state.projections["tabletop.entities"][key]
    activity = Activity.model_validate(state.projections[ACTIVITIES][key])
    elapsed = until - row["updated_seconds"]
    activity = recover(
        activity, body, row["updated_seconds"], until, allowed=activity.status == "RUNNING"
    )
    if int(body.get("hp", 0)) > 0:
        body["hunger"] = int(body.get("hunger", 0)) + elapsed
    if activity.status == "RUNNING" and int(body.get("hp", 0)) > 0:
        progress = activity.progress_seconds + elapsed
        if activity.kind in {"WEED", "TRAVEL"}:
            body["fatigue"] = int(body.get("fatigue", 0)) + elapsed
        elif activity.kind in {"REST", "SLEEP"}:
            fatigue = int(body.get("fatigue", 0))
            body["fatigue"] = max(0, fatigue - elapsed * (2 if activity.kind == "SLEEP" else 1))
            activity = activity.account(ActivityOutputs(fatigue_relieved=fatigue - body["fatigue"]))
        if activity.kind == "WEED":
            body["weeded_units"] = int(body.get("weeded_units", 0)) + elapsed
            activity = activity.account(ActivityOutputs(weeded_units=elapsed))
        elif activity.kind == "SLEEP":
            body["sleep_seconds"] = int(body.get("sleep_seconds", 0)) + elapsed
            activity = activity.account(ActivityOutputs(sleep_seconds=elapsed))
        elif activity.kind == "SOCIAL":
            obligation = state.projections[OBLIGATIONS][activity.details["obligation_id"]]
            progress = obligation["progress_seconds"]
            activity = activity.account(ActivityOutputs(social_seconds=elapsed))
        elif activity.kind == "TRAVEL":
            details = dict(activity.details)
            details["step_progress"] += elapsed
            if details["step_progress"] == row["life"]["step_seconds"]:
                target, actual = details["path"][details["index"]], position(state, key)
                result = move_entity(
                    state,
                    uuid.UUID(key),
                    MoveRequest(dx=target["x"] - actual["x"], dy=target["y"] - actual["y"]),
                )
                for delta in result.deltas:
                    state.apply(delta)
                details.update(
                    index=details["index"] + 1, expected=position(state, key), step_progress=0
                )
                body["travel_steps"] = int(body.get("travel_steps", 0)) + 1
                activity = activity.account(ActivityOutputs(travel_steps=1))
            activity = activity.model_copy(update={"details": details})
        complete = progress >= activity.duration_seconds
        if activity.details.get("planning_goal") and activity.kind in {"WEED", "REST"}:
            goal = activity.details["planning_goal"]
            planner = row["planner"]
            planner["spent"][goal] = planner["spent"].get(goal, 0) + elapsed
        if complete and activity.kind == "EAT":
            activity = eat_meal(activity, body)
        activity = activity.evolve(
            updated_seconds=until,
            progress_seconds=progress,
            status="COMPLETED" if complete else "RUNNING",
        )
        records[activity.activity_id] = activity
    elif activity.status == "WAITING":
        activity = activity.evolve(updated_seconds=until)
        if activity.activity_id in records:
            records[activity.activity_id] = activity
    state.projections[ACTIVITIES][key] = activity.model_dump(mode="json")
    row["updated_seconds"] = until


def advance_life(
    state: BranchState, until: int, records: ActivityRecords, start: int | None = None
) -> None:
    from population.routines import advance_body, reconcile_relevance

    routines = state.projections.get("tabletop.routines", {})
    now = (
        start
        if start is not None
        else min(
            (row["updated_seconds"] for row in routines.values() if row["enabled"]),
            default=seconds(state),
        )
    )
    if any(row["enabled"] and row["updated_seconds"] > now for row in routines.values()):
        raise ValueError("routine time cannot move backward")
    while True:
        finish_obligations(state, now)
        for key, row in sorted(routines.items()):
            if row["enabled"] and row.get("life"):
                prepare(state, key, row, now)
        for identity, obligation in sorted(state.projections.get(OBLIGATIONS, {}).items()):
            if obligation["status"] in {"COMPLETED", "MISSED", "CANCELLED"}:
                continue
            present = ready(state, identity, obligation, now)
            obligation["status"] = "ATTENDING" if present else "WAITING"
            if present and obligation["started_seconds"] is None:
                obligation["started_seconds"] = now
            for key in obligation["participants"]:
                activity = state.projections.get(ACTIVITIES, {}).get(key)
                if (
                    activity
                    and activity["kind"] == "SOCIAL"
                    and activity["details"]["obligation_id"] == identity
                ):
                    state.projections[ACTIVITIES][key] = (
                        Activity.model_validate(activity)
                        .evolve(
                            status="RUNNING" if present else "WAITING",
                            reason=None
                            if present
                            else "NOT_STARTED"
                            if now < obligation["starts_seconds"]
                            else "PARTNER_UNAVAILABLE",
                        )
                        .model_dump(mode="json")
                    )
        reconcile_relevance(state, now)
        if now == until:
            break
        stop = next_boundary(state, now, until)
        for obligation in state.projections.get(OBLIGATIONS, {}).values():
            if obligation["status"] == "ATTENDING":
                obligation["progress_seconds"] += stop - now
                for key in obligation["participants"]:
                    body = state.projections["tabletop.entities"][key]
                    body["social_seconds"] = int(body.get("social_seconds", 0)) + stop - now
        for key, row in sorted(routines.items()):
            if row["enabled"]:
                if row.get("life"):
                    progress_body(state, key, row, stop, records)
                else:
                    advance_body(state, key, row, stop, records)
        now = stop
