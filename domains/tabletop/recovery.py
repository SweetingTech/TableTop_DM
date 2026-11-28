"""Clock-driven death saves. Physical outcomes own the seed; callers cannot roll for a body."""

from __future__ import annotations

import hashlib
import random
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from domains.tabletop.action_time import ROUND_SECONDS
from domains.tabletop.effects import clock_now
from domains.tabletop.rules import dead
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from kernel.command_bus import CommandDefinition, CommandHandler
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.errors import AuthorizationDenied
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState

VITALS = "tabletop.vitals"
RECOVERY_VERSION = "tabletop-recovery-1.0.0"
STABLE_RECOVERY_SECONDS = 3600


class VitalState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rules_version: str = RECOVERY_VERSION
    run_id: uuid.UUID
    source_command_id: uuid.UUID
    seed: int = Field(ge=0)
    status: Literal["DYING", "STABLE", "DEAD", "RECOVERED"] = "DYING"
    successes: int = Field(default=0, ge=0, le=3)
    failures: int = Field(default=0, ge=0, le=3)
    rolls: tuple[int, ...] = Field(default=(), max_length=5)
    next_save_seconds: int | None = Field(default=None, ge=0)
    recovery_seconds: int | None = Field(default=None, ge=0)


def save_roll(seed: int, entity_id: uuid.UUID, index: int) -> int:
    material = f"{RECOVERY_VERSION}:{seed}:{entity_id}:{index}".encode()
    return random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big")).randint(1, 20)


def _stable(row: VitalState, body: dict, now: int | None) -> VitalState:
    return row.model_copy(
        update={
            "status": "STABLE",
            "next_save_seconds": None,
            "recovery_seconds": now + STABLE_RECOVERY_SECONDS
            if now is not None and int(body.get("max_hp", 0)) > 0
            else None,
        }
    )


def boundaries(state: BranchState, start: int, until: int) -> tuple[int, ...]:
    points: set[int] = set()
    for raw in state.projections.get(VITALS, {}).values():
        row = VitalState.model_validate(raw)
        if row.status == "DYING":
            first = (
                row.next_save_seconds
                if row.next_save_seconds is not None
                else start + ROUND_SECONDS
            )
            for index in range(5 - len(row.rolls)):
                at = first + index * ROUND_SECONDS
                points.update((at, at + STABLE_RECOVERY_SECONDS))
        elif row.status == "STABLE":
            recovery_at = row.recovery_seconds
            if recovery_at is None:
                continue
            points.add(recovery_at)
    return tuple(sorted(point for point in points if start < point <= until))


def advance(state: BranchState, now: int) -> None:
    """Called only on the clock handler's private working state, including exact boundaries."""
    rows = state.projections.get(VITALS, {})
    for key, raw in sorted(tuple(rows.items())):
        row = VitalState.model_validate(raw)
        body = state.projections.get("tabletop.entities", {}).get(key)
        if body is None:
            raise ValueError("recovery body is unavailable")
        if dead(body):
            rows[key] = row.model_copy(
                update={"status": "DEAD", "next_save_seconds": None, "recovery_seconds": None}
            ).model_dump(mode="json")
            continue
        if int(body.get("hp", 0)) > 0:
            if row.status != "RECOVERED":
                del rows[key]
            continue
        if row.status == "DYING" and row.next_save_seconds is None:
            row = row.model_copy(update={"next_save_seconds": now + ROUND_SECONDS})
        elif row.status == "STABLE" and row.recovery_seconds is None:
            row = _stable(row, body, now)
        while (
            row.status == "DYING"
            and row.next_save_seconds is not None
            and row.next_save_seconds <= now
        ):
            at = row.next_save_seconds
            roll = save_roll(row.seed, uuid.UUID(key), len(row.rolls))
            row = row.model_copy(update={"rolls": (*row.rolls, roll)})
            if roll == 20:
                body.update(hp=1, defeated=False)
                row = row.model_copy(
                    update={
                        "status": "RECOVERED",
                        "next_save_seconds": None,
                        "recovery_seconds": None,
                    }
                )
                break
            if roll >= 10:
                row = row.model_copy(update={"successes": min(3, row.successes + 1)})
            else:
                row = row.model_copy(
                    update={"failures": min(3, row.failures + (2 if roll == 1 else 1))}
                )
            if row.failures == 3:
                body.update(dead=True, defeated=True, guarded=False, asleep=False)
                row = row.model_copy(update={"status": "DEAD", "next_save_seconds": None})
            elif row.successes == 3:
                row = _stable(row, body, at)
            else:
                row = row.model_copy(update={"next_save_seconds": at + ROUND_SECONDS})
        if int(body.get("hp", 0)) > 0:
            rows[key] = row.model_dump(mode="json")
            continue
        if (
            row.status == "STABLE"
            and row.recovery_seconds is not None
            and row.recovery_seconds <= now
        ):
            if int(body.get("max_hp", 0)) > 0:
                body.update(hp=1, defeated=False)
                rows[key] = row.model_copy(
                    update={"status": "RECOVERED", "recovery_seconds": None}
                ).model_dump(mode="json")
                continue
        rows[key] = row.model_dump(mode="json")


def with_recovery(handler: CommandHandler) -> CommandHandler:
    def execute(proposal: CommandProposal, state: BranchState) -> CommandResult:
        result = handler(proposal, state)
        if not result.accepted:
            return result
        after = state.working_copy()
        for delta in result.deltas:
            after.apply(delta)
        updates: list[StateDelta] = []
        for key, body in sorted(after.projections.get("tabletop.entities", {}).items()):
            old = state.projections.get("tabletop.entities", {}).get(key)
            if old is None or dead(old) or dead(body) or "hp" not in old or "hp" not in body:
                continue
            before_hp, after_hp = int(old["hp"]), int(body["hp"])
            if before_hp <= 0 < after_hp:
                values: dict = {"defeated": False}
                if str(body.get("status", "")).upper() == "DEFEATED":
                    values["status"] = "ACTIVE"
                updates.append(
                    StateDelta(
                        projection="tabletop.entities",
                        operation="MERGE",
                        entity_id=uuid.UUID(key),
                        values=values,
                    )
                )
                if key in after.projections.get(VITALS, {}):
                    updates.append(
                        StateDelta(projection=VITALS, operation="DELETE", entity_id=uuid.UUID(key))
                    )
            elif before_hp > 0 and after_hp == 0:
                if proposal.seed is None:
                    raise ValueError("defeat requires trusted physical-action randomness")
                now = clock_now(state, proposal.run_id)
                row = VitalState(
                    run_id=proposal.run_id,
                    source_command_id=proposal.command_id,
                    seed=proposal.seed,
                    next_save_seconds=None if now is None else now + ROUND_SECONDS,
                )
                updates.append(
                    StateDelta(
                        projection=VITALS,
                        operation="SET",
                        entity_id=uuid.UUID(key),
                        values=row.model_dump(mode="json"),
                    )
                )
            elif (
                before_hp == after_hp == 0 and str(proposal.parameters.get("target_id", "")) == key
            ):
                damage = (
                    int(result.result.get("damage", 0))
                    if proposal.command_type == "tabletop.combat.attack"
                    else (
                        int(result.result.get("power", 0))
                        if proposal.command_type in {"tabletop.magic.cast", "tabletop.magic.invoke"}
                        and result.result.get("effect") == "DAMAGE"
                        else 0
                    )
                )
                if damage <= 0:
                    continue
                now = clock_now(state, proposal.run_id)
                raw = after.projections.get(VITALS, {}).get(key)
                row = (
                    VitalState.model_validate(raw)
                    if raw
                    else VitalState(
                        run_id=proposal.run_id,
                        source_command_id=proposal.command_id,
                        seed=proposal.seed if proposal.seed is not None else 0,
                    )
                )
                if row.status == "STABLE":
                    row = VitalState(
                        run_id=proposal.run_id,
                        source_command_id=proposal.command_id,
                        seed=proposal.seed if proposal.seed is not None else 0,
                    )
                failures = min(
                    3, row.failures + (2 if result.result.get("attack_roll") == 20 else 1)
                )
                row = row.model_copy(
                    update={
                        "failures": failures,
                        "recovery_seconds": None,
                        "status": "DEAD" if failures == 3 else "DYING",
                        "next_save_seconds": None
                        if failures == 3 or now is None
                        else (
                            row.next_save_seconds
                            if row.next_save_seconds is not None
                            else now + ROUND_SECONDS
                        ),
                    }
                )
                if failures == 3:
                    updates.append(
                        StateDelta(
                            projection="tabletop.entities",
                            operation="MERGE",
                            entity_id=uuid.UUID(key),
                            values={
                                "dead": True,
                                "defeated": True,
                                "guarded": False,
                                "asleep": False,
                            },
                        )
                    )
                updates.append(
                    StateDelta(
                        projection=VITALS,
                        operation="SET",
                        entity_id=uuid.UUID(key),
                        values=row.model_dump(mode="json"),
                    )
                )
        return result.model_copy(update={"deltas": (*result.deltas, *updates)})

    return execute


class StabilizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: uuid.UUID


class StabilizeResult(BaseModel):
    target_id: uuid.UUID
    status: Literal["STABLE"]


def stabilize(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = StabilizeRequest.model_validate(proposal.parameters)
    target = state.projections.get("tabletop.entities", {}).get(str(request.target_id))
    if target is None or dead(target) or int(target.get("hp", -1)) != 0:
        raise ValueError("stabilization requires a living defeated body")
    if proposal.embodied_entity_id is None or proposal.embodied_entity_id == request.target_id:
        raise ValueError("another capable body must provide first aid")
    visible = GridSpatialPerceptionResolver().visible_entities(state, proposal.embodied_entity_id)
    positions = state.projections.get("tabletop.spatial.positions", {})
    origin = positions.get(str(proposal.embodied_entity_id), {})
    destination = positions.get(str(request.target_id), {})
    if (
        request.target_id not in visible
        or not origin
        or not destination
        or origin.get("zone_id", "world") != destination.get("zone_id", "world")
        or max(abs(int(origin.get(axis, 0)) - int(destination.get(axis, 0))) for axis in ("x", "y"))
        > 1
    ):
        raise ValueError("stabilization requires visible adjacent contact")
    raw = state.projections.get(VITALS, {}).get(str(request.target_id))
    row = (
        VitalState.model_validate(raw)
        if raw is not None
        else VitalState(run_id=proposal.run_id, source_command_id=proposal.command_id, seed=0)
    )
    if row.status != "DYING":
        raise ValueError("body is already stable")
    row = _stable(row, target, clock_now(state, proposal.run_id))
    return CommandResult(
        result={"target_id": str(request.target_id), "status": "STABLE"},
        deltas=(
            StateDelta(
                projection=VITALS,
                operation="SET",
                entity_id=request.target_id,
                values=row.model_dump(mode="json"),
            ),
        ),
        domain_tags=("tabletop", "stabilize"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.combat.stabilize",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=stabilize,
        request_model=StabilizeRequest,
        result_model=StabilizeResult,
        requires_controlled_entity=True,
        emission_builder=lambda proposal, result, before, after: EventEmission(
            anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="BEFORE"),
            modalities=(SensoryModality.SIGHT,),
            max_range=2,
            allowed_payload_fields=("target_id", "status"),
            reason_codes=("body.first_aid",),
        ),
    )


class ResurrectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_id: uuid.UUID
    hit_points: int = Field(default=1, strict=True, ge=1)


class ResurrectResult(BaseModel):
    target_id: uuid.UUID
    summary: Literal["The body returns to life."] = "The body returns to life."


def resurrect(proposal: CommandProposal, state: BranchState) -> CommandResult:
    if proposal.input_origin != "OPERATOR" or proposal.embodied_entity_id is not None:
        raise AuthorizationDenied("resurrection requires operator authority")
    request = ResurrectRequest.model_validate(proposal.parameters)
    key = str(request.target_id)
    body = state.projections.get("tabletop.entities", {}).get(key)
    if body is None or not dead(body):
        raise ValueError("resurrection requires an existing dead body")
    if request.hit_points > int(body.get("max_hp", 0)):
        raise ValueError("resurrection hit points exceed the body's maximum")
    restored: dict[str, JsonValue] = {
        "hp": request.hit_points,
        "dead": False,
        "defeated": False,
        "guarded": False,
        "asleep": False,
    }
    conditions = body.get("conditions", ())
    remaining = [condition for condition in conditions if str(condition).casefold() != "dead"]
    if len(remaining) != len(conditions):
        restored["conditions"] = remaining
    if str(body.get("status", "")).upper() in {"DEAD", "DEFEATED"}:
        restored["status"] = "ACTIVE"
    deltas = [
        StateDelta(
            projection="tabletop.entities",
            operation="MERGE",
            entity_id=request.target_id,
            values=restored,
        )
    ]
    raw = state.projections.get(VITALS, {}).get(key)
    if raw is not None:
        row = VitalState.model_validate(raw).model_copy(
            update={"status": "RECOVERED", "next_save_seconds": None, "recovery_seconds": None}
        )
        deltas.append(
            StateDelta(
                projection=VITALS,
                operation="SET",
                entity_id=request.target_id,
                values=row.model_dump(mode="json"),
            )
        )
    return CommandResult(
        result=ResurrectResult(target_id=request.target_id).model_dump(mode="json"),
        deltas=tuple(deltas),
        domain_tags=("tabletop", "recovery", "resurrection"),
    )


def resurrection_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.recovery.resurrect",
        required_capabilities=frozenset({"action.propose", "world.read.all", "entity.control"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
        handler=resurrect,
        request_model=ResurrectRequest,
        result_model=ResurrectResult,
        emission_builder=lambda proposal, result, before, after: EventEmission(
            anchor=SpatialAnchor(entity_id=uuid.UUID(result.result["target_id"]), phase="AFTER"),
            modalities=(SensoryModality.SIGHT,),
            max_range=8,
            allowed_payload_fields=("target_id", "summary"),
            reason_codes=("body.resurrection",),
        ),
    )
