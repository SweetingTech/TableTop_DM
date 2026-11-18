"""Small persistent activity vocabulary; canonical bodies own all resulting resources."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.action_time import wait_seconds
from domains.tabletop.effects import anchor_legacy_blessings, boundaries, expire
from domains.tabletop.rules import incapacitated
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

ACTIVITIES = "tabletop.activities"
WEATHER = "tabletop.weather"
SCHEDULE = "tabletop.weather_schedule"


class ActivityInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    food: int = Field(default=0, ge=0)


class ActivityOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    weeded_units: int = Field(default=0, ge=0)
    meals_eaten: int = Field(default=0, ge=0)
    hunger_relieved: int = Field(default=0, ge=0)
    fatigue_relieved: int = Field(default=0, ge=0)
    hp_restored: int = Field(default=0, ge=0)
    mana_restored: int = Field(default=0, ge=0)
    travel_steps: int = Field(default=0, ge=0)
    sleep_seconds: int = Field(default=0, ge=0)
    social_seconds: int = Field(default=0, ge=0)


def activity_due(fields: dict) -> int | None:
    if fields["status"] == "COMPLETED":
        return fields["updated_seconds"]
    if fields["status"] == "RUNNING":
        return fields["updated_seconds"] + max(
            0, fields["duration_seconds"] - fields["progress_seconds"]
        )
    return None


class ActivityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    activity_id: uuid.UUID
    entity_id: uuid.UUID
    kind: Literal["WEED", "REST", "EAT", "TRAVEL", "SLEEP", "SOCIAL"]
    duration_seconds: int = Field(ge=1, le=86400)
    started_seconds: int = Field(ge=0)
    updated_seconds: int = Field(ge=0)
    progress_seconds: int = Field(default=0, ge=0)
    status: Literal["RUNNING", "WAITING", "COMPLETED", "CANCELLED"] = "RUNNING"
    reason: (
        Literal[
            "RAIN",
            "INCAPACITATED",
            "ACTION_BUSY",
            "MOVED",
            "NO_FOOD",
            "PATH_BLOCKED",
            "PARTNER_UNAVAILABLE",
            "NOT_STARTED",
            "DANGER",
        ]
        | None
    ) = None
    due_seconds: int | None = Field(default_factory=activity_due, ge=0)
    inputs: ActivityInputs = Field(default_factory=ActivityInputs)
    outputs: ActivityOutputs = Field(default_factory=ActivityOutputs)


class Activity(ActivityRecord):
    task_key: str | None = None
    details: dict = Field(default_factory=dict)
    routine_id: uuid.UUID | None = None
    origin: dict

    def evolve(self, **changes: object) -> Activity:
        updated = self.model_copy(update=changes)
        return updated.model_copy(
            update={
                "due_seconds": activity_due(
                    {
                        "status": updated.status,
                        "updated_seconds": updated.updated_seconds,
                        "duration_seconds": updated.duration_seconds,
                        "progress_seconds": updated.progress_seconds,
                    }
                )
            }
        )

    def account(self, outputs: ActivityOutputs, *, food: int = 0) -> Activity:
        increments = outputs.model_dump(exclude_defaults=True)
        if not increments and not food:
            return self
        return self.model_copy(
            update={
                "inputs": self.inputs.model_copy(update={"food": self.inputs.food + food}),
                "outputs": self.outputs.model_copy(
                    update={
                        name: getattr(self.outputs, name) + amount
                        for name, amount in increments.items()
                    }
                ),
            }
        )


ActivityRecords = dict[uuid.UUID, Activity]


def eat_meal(activity: Activity, body: dict) -> Activity:
    inventory = dict(body["inventory"])
    inventory["food"] = int(inventory["food"]) - 1
    body["inventory"] = inventory
    hunger = int(body["hunger"])
    body["hunger"] = max(0, hunger - 14400)
    body["meals_eaten"] = int(body.get("meals_eaten", 0)) + 1
    return activity.account(
        ActivityOutputs(meals_eaten=1, hunger_relieved=hunger - body["hunger"]), food=1
    )


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID
    kind: Literal["WEED", "REST"]
    duration_seconds: int = Field(default=3600, ge=1, le=86400)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID
    activity_id: uuid.UUID


class WeatherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_seconds: int = Field(ge=0)
    zone_id: str = Field(min_length=1, max_length=120)
    raining: bool


class CancelWeatherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_id: uuid.UUID


class ActivityResult(BaseModel):
    activity_id: uuid.UUID | None = None
    schedule_id: uuid.UUID | None = None


def position(state: BranchState, entity: str) -> dict:
    body = state.projections.get("tabletop.entities", {}).get(entity)
    if body is None:
        raise ValueError("activity requires an existing body")
    row = state.projections.get("tabletop.spatial.positions", {}).get(entity, body)
    return {
        "x": row.get("x", 0),
        "y": row.get("y", 0),
        "z": row.get("z", 0),
        "zone_id": str(row.get("zone_id", "world")),
    }


def seconds(state: BranchState) -> int:
    clock = state.projections.get("tabletop.clock", {}).get("singleton")
    if clock is None:
        raise ValueError("configure the world clock first")
    return int(clock["seconds"])


def start(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = StartRequest.model_validate(proposal.parameters)
    now = seconds(state)
    key = str(request.entity_id)
    body = state.projections.get("tabletop.entities", {}).get(key)
    origin = position(state, key)
    if body is None or int(body.get("hp", 0)) <= 0 or incapacitated(body):
        raise ValueError("activity requires a capable body")
    rows = state.projections.get(ACTIVITIES, {})
    if state.projections.get("tabletop.routines", {}).get(key, {}).get("enabled"):
        raise ValueError("disable the body routine before starting a manual activity")
    if key in rows and rows[key]["status"] in {"RUNNING", "WAITING"}:
        raise ValueError("cancel the existing activity first")
    if key not in rows and len(rows) >= 256:
        raise ValueError("activity body limit reached")
    activity = Activity(
        activity_id=uuid.uuid5(
            proposal.run_id, f"activity:{proposal.actor_id}:{proposal.idempotency_key}"
        ),
        entity_id=request.entity_id,
        kind=request.kind,
        duration_seconds=request.duration_seconds,
        started_seconds=now,
        updated_seconds=now,
        origin=origin,
    )
    return CommandResult(
        result={"activity_id": str(activity.activity_id)},
        deltas=(
            StateDelta(
                projection=ACTIVITIES,
                operation="SET",
                entity_id=request.entity_id,
                values=activity.model_dump(mode="json"),
            ),
        ),
        domain_tags=("operator", "activity_configuration"),
    )


def cancel(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = CancelRequest.model_validate(proposal.parameters)
    row = state.projections.get(ACTIVITIES, {}).get(str(request.entity_id))
    if row is None or row["activity_id"] != str(request.activity_id):
        raise ValueError("activity changed")
    if (
        state.projections.get("tabletop.routines", {})
        .get(str(request.entity_id), {})
        .get("enabled")
    ):
        raise ValueError("disable the body routine before cancelling its activity")
    return CommandResult(
        result={"activity_id": str(request.activity_id)},
        deltas=(
            StateDelta(
                projection=ACTIVITIES,
                operation="SET",
                entity_id=request.entity_id,
                values=Activity.model_validate(row)
                .evolve(status="CANCELLED", reason=None, updated_seconds=seconds(state))
                .model_dump(mode="json"),
            ),
        ),
        domain_tags=("operator", "activity_configuration"),
    )


def schedule_weather(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = WeatherRequest.model_validate(proposal.parameters)
    if request.due_seconds < seconds(state):
        raise ValueError("weather cannot be scheduled in the past")
    if request.zone_id != "world" and request.zone_id not in state.projections.get(
        "tabletop.spatial.zones", {}
    ):
        raise ValueError("unknown weather zone")
    pending = state.projections.get(SCHEDULE, {})
    if len(pending) >= 128:
        raise ValueError("pending weather limit reached")
    identity = uuid.uuid5(
        proposal.run_id, f"weather:{proposal.actor_id}:{proposal.idempotency_key}"
    )
    return CommandResult(
        result={"schedule_id": str(identity)},
        deltas=(
            StateDelta(
                projection=SCHEDULE,
                operation="SET",
                entity_id=identity,
                values={
                    **request.model_dump(),
                    "order": max((int(row["order"]) for row in pending.values()), default=-1) + 1,
                },
            ),
        ),
        domain_tags=("operator", "weather_schedule"),
    )


def cancel_weather(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = CancelWeatherRequest.model_validate(proposal.parameters)
    if str(request.schedule_id) not in state.projections.get(SCHEDULE, {}):
        raise ValueError("weather schedule is no longer pending")
    return CommandResult(
        result={"schedule_id": str(request.schedule_id)},
        deltas=(
            StateDelta(projection=SCHEDULE, operation="DELETE", entity_id=request.schedule_id),
        ),
        domain_tags=("operator", "weather_schedule"),
    )


def progress(state: BranchState, until: int, records: ActivityRecords | None = None) -> None:
    """Advance a private working copy; never persist or inspect cameras/minds."""
    from domains.tabletop.rest import recover

    if records is None:
        records = {}
    for key, raw in sorted(state.projections.get(ACTIVITIES, {}).items()):
        activity = Activity.model_validate(raw)
        if activity.routine_id is not None:
            continue
        if activity.status in {"COMPLETED", "CANCELLED"}:
            continue
        body = state.projections["tabletop.entities"].get(key)
        reason = (
            "INCAPACITATED"
            if body is None or int(body.get("hp", 0)) <= 0 or incapacitated(body)
            else "ACTION_BUSY"
            if wait_seconds(state, activity.entity_id, at_seconds=activity.updated_seconds)
            else "MOVED"
            if position(state, key) != activity.origin
            else "RAIN"
            if activity.kind == "WEED"
            and state.projections.get(WEATHER, {})
            .get("singleton", {})
            .get(activity.origin["zone_id"], False)
            else None
        )
        elapsed = 0
        if reason is None:
            if activity.due_seconds is None:
                activity = activity.evolve(status="RUNNING", reason=None)
            assert activity.due_seconds is not None
            elapsed = min(until, activity.due_seconds) - activity.updated_seconds
        if elapsed < 0:
            raise ValueError("activity time cannot move backward")
        if body is not None:
            activity = recover(
                activity,
                body,
                activity.updated_seconds,
                activity.updated_seconds + elapsed,
                allowed=reason is None,
            )
        if elapsed and body is not None:
            if activity.kind == "WEED":
                body["weeded_units"] = int(body.get("weeded_units", 0)) + elapsed
                activity = activity.account(ActivityOutputs(weeded_units=elapsed))
            else:
                fatigue = int(body.get("fatigue", 0))
                body["fatigue"] = max(0, fatigue - elapsed)
                activity = activity.account(
                    ActivityOutputs(fatigue_relieved=fatigue - body["fatigue"])
                )
        total = activity.progress_seconds + elapsed
        complete = total == activity.duration_seconds
        updated = activity.evolve(
            progress_seconds=total,
            updated_seconds=activity.updated_seconds + elapsed if complete else until,
            status=(
                "CANCELLED"
                if reason and activity.details.get("rest_kind")
                else "COMPLETED"
                if complete
                else "WAITING"
                if reason
                else "RUNNING"
            ),
            reason=reason,
        )
        state.projections[ACTIVITIES][key] = updated.model_dump(mode="json")
        if elapsed or updated.activity_id in records:
            records[updated.activity_id] = updated


def advance_activities(state: BranchState, until: int) -> ActivityRecords:
    from domains.tabletop.rest import boundaries as rest_boundaries
    from population.routines import advance_routines, reconcile_relevance

    cursor = seconds(state)
    reconcile_relevance(state, cursor)
    anchor_legacy_blessings(state, cursor)
    expire(state, cursor)
    pending = state.projections.get(SCHEDULE, {})
    weather = sorted(
        tuple(pending.items()), key=lambda item: (item[1]["due_seconds"], item[1]["order"], item[0])
    )

    def apply_weather(now: int) -> None:
        for key, row in weather:
            if key in pending and row["due_seconds"] <= now:
                state.projections.setdefault(WEATHER, {}).setdefault("singleton", {})[
                    row["zone_id"]
                ] = row["raining"]
                del pending[key]

    records: ActivityRecords = {}
    apply_weather(cursor)
    progress(state, cursor, records)
    advance_routines(state, cursor, records, cursor)
    stops = (
        set(boundaries(state, cursor, until))
        | set(rest_boundaries(state, cursor, until))
        | {int(row["due_seconds"]) for _, row in weather if cursor < row["due_seconds"] <= until}
    )
    for stop in sorted(stops):
        progress(state, stop, records)
        advance_routines(state, stop, records, cursor)
        expire(state, stop)
        apply_weather(stop)
        # Reconcile without elapsed work so split and whole advances agree at the boundary.
        progress(state, stop, records)
        advance_routines(state, stop, records, stop)
        cursor = stop
    return records


def command_definitions() -> tuple[CommandDefinition, ...]:
    return tuple(
        CommandDefinition(
            command_type=name,
            required_capabilities=frozenset({"action.propose", "entity.control"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=handler,
            request_model=model,
            result_model=ActivityResult,
        )
        for name, handler, model in (
            ("tabletop.activity.start", start, StartRequest),
            ("tabletop.activity.cancel", cancel, CancelRequest),
            ("tabletop.weather.schedule", schedule_weather, WeatherRequest),
            ("tabletop.weather.cancel", cancel_weather, CancelWeatherRequest),
        )
    )
