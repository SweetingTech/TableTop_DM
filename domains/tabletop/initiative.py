"""Seeded initiative windows on the same clock as movement, work and recovery."""

from __future__ import annotations

import hashlib
import random
import uuid

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.action_time import ROUND_SECONDS
from domains.tabletop.rules import AbilityScores, dead
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.errors import BodyActionPending
from kernel.randomness import ActionRandomness
from kernel.state import BranchState

ENCOUNTERS = "tabletop.encounters"
INITIATIVE_VERSION = "tabletop-initiative-1.0.0"
SOCIAL_COMMANDS = frozenset(
    {"tabletop.dialogue.speak", "tabletop.console.submit", "tabletop.quest.advance"}
)


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    participants: tuple[uuid.UUID, ...] = Field(min_length=2, max_length=64)


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encounter_id: uuid.UUID


class InitiativeRoll(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entity_id: uuid.UUID
    roll: int = Field(ge=1, le=20)
    bonus: int = Field(ge=-5, le=10)
    total: int


class Encounter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    encounter_id: uuid.UUID
    run_id: uuid.UUID
    source_command_id: uuid.UUID
    rules_version: str = INITIATIVE_VERSION
    started_seconds: int = Field(ge=0)
    order: tuple[InitiativeRoll, ...] = Field(min_length=2, max_length=64)
    active: bool = True


class EncounterResult(BaseModel):
    encounter_id: uuid.UUID
    active: bool
    order: tuple[InitiativeRoll, ...]
    randomness: ActionRandomness | None = None


def active(state: BranchState) -> tuple[Encounter, ...]:
    return tuple(
        Encounter.model_validate(raw)
        for _, raw in sorted(state.projections.get(ENCOUNTERS, {}).items())
        if raw["active"]
    )


def membership(state: BranchState, entity_id: uuid.UUID) -> Encounter | None:
    return next(
        (row for row in active(state) if any(item.entity_id == entity_id for item in row.order)),
        None,
    )


def clock(state: BranchState, run_id: uuid.UUID) -> int:
    row = state.projections.get("tabletop.clock", {}).get("singleton")
    if row is None or str(row["run_id"]) != str(run_id):
        raise ValueError("initiative requires the current run's world clock")
    return int(row["seconds"])


def start(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = StartRequest.model_validate(proposal.parameters)
    now = clock(state, proposal.run_id)
    if proposal.seed is None:
        raise ValueError("initiative requires a recorded kernel seed")
    if len(set(request.participants)) != len(request.participants):
        raise ValueError("encounter participants must be distinct")
    if len(active(state)) >= 32:
        raise ValueError("encounter limit reached")
    bodies = state.projections.get("tabletop.entities", {})
    rolls = []
    for entity_id in sorted(request.participants):
        body = bodies.get(str(entity_id))
        if body is None or dead(body) or int(body.get("hp", 0)) <= 0:
            raise ValueError("initiative requires existing living participants")
        if membership(state, entity_id) is not None:
            raise ValueError("body already participates in an active encounter")
        dexterity = AbilityScores.model_validate(body.get("ability_scores", {})).dexterity
        material = f"{INITIATIVE_VERSION}:{proposal.seed}:{entity_id}".encode()
        roll = random.Random(int.from_bytes(hashlib.sha256(material).digest(), "big")).randint(
            1, 20
        )
        bonus = (dexterity - 10) // 2
        rolls.append(
            InitiativeRoll(entity_id=entity_id, roll=roll, bonus=bonus, total=roll + bonus)
        )
    order = tuple(sorted(rolls, key=lambda row: (-row.total, -row.bonus, str(row.entity_id))))
    identity = uuid.uuid5(
        proposal.run_id, f"initiative:{proposal.actor_id}:{proposal.idempotency_key}"
    )
    row = Encounter(
        encounter_id=identity,
        run_id=proposal.run_id,
        source_command_id=proposal.command_id,
        started_seconds=now,
        order=order,
    )
    return CommandResult(
        result=EncounterResult(encounter_id=identity, active=True, order=order).model_dump(
            mode="json"
        ),
        deltas=(
            StateDelta(
                projection=ENCOUNTERS,
                operation="SET",
                entity_id=identity,
                values=row.model_dump(mode="json"),
            ),
        ),
        domain_tags=("operator", "initiative"),
    )


def stop(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = StopRequest.model_validate(proposal.parameters)
    clock(state, proposal.run_id)
    raw = state.projections.get(ENCOUNTERS, {}).get(str(request.encounter_id))
    if raw is None or not raw["active"]:
        raise ValueError("encounter is not active")
    row = Encounter.model_validate(raw)
    return CommandResult(
        result=EncounterResult(
            encounter_id=row.encounter_id, active=False, order=row.order
        ).model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection=ENCOUNTERS,
                operation="DELETE",
                entity_id=row.encounter_id,
            ),
        ),
        domain_tags=("operator", "initiative"),
    )


def wait_for_turn(state: BranchState, entity_id: uuid.UUID, at_seconds: int) -> int:
    encounter = membership(state, entity_id)
    current = state.projections.get("tabletop.clock", {}).get("singleton", {})
    if encounter is None or str(encounter.run_id) != str(current.get("run_id")):
        return 0
    index = next(i for i, item in enumerate(encounter.order) if item.entity_id == entity_id)
    elapsed = max(0, at_seconds - encounter.started_seconds)
    slot = elapsed // ROUND_SECONDS
    current_index = slot % len(encounter.order)
    if current_index == index:
        return 0
    next_slot = slot + (index - current_index) % len(encounter.order)
    return encounter.started_seconds + next_slot * ROUND_SECONDS - at_seconds


def validate_attempt(proposal: CommandProposal, state: BranchState) -> None:
    if proposal.command_type in SOCIAL_COMMANDS:
        return
    entity_id = proposal.embodied_entity_id
    if entity_id is None:
        return  # The ordinary entity-control boundary provides the canonical error.
    encounter = membership(state, entity_id)
    if encounter is not None:
        if encounter.run_id != proposal.run_id:
            raise ValueError("end the previous run's encounter before acting")
        if proposal.command_type == "tabletop.rest.start":
            raise ValueError("finish the encounter before starting a rest")
        now = clock(state, proposal.run_id)
        if wait_for_turn(state, entity_id, now):
            raise BodyActionPending("body is waiting for its initiative window")
    for name in ("target_id", "counterparty_id"):
        target = proposal.parameters.get(name)
        if target is None:
            continue
        other = membership(state, uuid.UUID(str(target)))
        if other is not None and (
            encounter is None or encounter.encounter_id != other.encounter_id
        ):
            raise ValueError(
                "join the target's encounter through its world manager before physical interaction"
            )


def boundaries(state: BranchState, start: int, until: int) -> tuple[int, ...]:
    points: set[int] = set()
    run_id = str(state.projections.get("tabletop.clock", {}).get("singleton", {}).get("run_id"))
    for encounter in active(state):
        if str(encounter.run_id) != run_id:
            continue
        first = (
            encounter.started_seconds
            + ((start - encounter.started_seconds) // ROUND_SECONDS + 1) * ROUND_SECONDS
        )
        points.update(range(max(first, encounter.started_seconds), until + 1, ROUND_SECONDS))
    return tuple(sorted(points))


def command_definitions() -> tuple[CommandDefinition, ...]:
    return tuple(
        CommandDefinition(
            command_type=name,
            version=INITIATIVE_VERSION,
            required_capabilities=frozenset({"action.propose", "entity.control"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=handler,
            request_model=model,
            result_model=EncounterResult,
            uses_randomness=name == "tabletop.encounter.start",
        )
        for name, handler, model in (
            ("tabletop.encounter.start", start, StartRequest),
            ("tabletop.encounter.stop", stop, StopRequest),
        )
    )
