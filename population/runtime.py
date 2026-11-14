"""Private branch-local population identities. Bodies alone own physical resources."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import (
    BranchKind,
    CommandProposal,
    CommandResult,
    PopulationBindingMutation,
    StateDelta,
)
from kernel.state import BranchState
from population.lifecycle import PopulationLifecycle
from population.models import PopulationLevel, PopulationMember, PopulationTransition

MEMBERS = "tabletop.population"
HISTORY = "tabletop.population_transitions"
MENTAL_FIELDS = frozenset({"beliefs", "memories", "relationships", "history"})


def source_hash(member: PopulationMember) -> str:
    return hashlib.sha256(
        json.dumps(member.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def scoped_member(state: BranchState, raw: dict) -> PopulationMember:
    return PopulationMember.model_validate(
        {**raw, "world_id": state.world_id, "branch_id": state.branch_id}
    )


def lifecycle_for(state: BranchState, persona_id: uuid.UUID) -> PopulationLifecycle:
    lifecycle = PopulationLifecycle(state.world_id, state.branch_id)
    row = state.projections.get(MEMBERS, {}).get(str(persona_id))
    if row is None:
        raise ValueError("population member is not bound in this branch")
    history = [
        PopulationTransition.model_validate(
            {**raw, "world_id": state.world_id, "branch_id": state.branch_id}
        )
        for raw in state.projections.get(HISTORY, {}).values()
        if raw["persona_id"] == str(persona_id)
    ]
    lifecycle.restore([scoped_member(state, row["member"])], history)
    return lifecycle


def save_lifecycle(
    state: BranchState, lifecycle: PopulationLifecycle, persona_id: uuid.UUID
) -> None:
    state.projections[MEMBERS][str(persona_id)]["member"] = lifecycle.get(persona_id).model_dump(
        mode="json", exclude={"world_id", "branch_id"}
    )
    for item in lifecycle.history:
        state.projections.setdefault(HISTORY, {})[str(item.transition_id)] = item.model_dump(
            mode="json", exclude={"world_id", "branch_id"}
        )


def world_step(row: dict, now: int) -> int:
    return int(row["source_world_step"]) + now - int(row["bound_at_seconds"])


def transition(
    state: BranchState, persona_id: uuid.UUID, level: PopulationLevel, now: int, reason: str
) -> PopulationMember:
    lifecycle = lifecycle_for(state, persona_id)
    before = lifecycle.get(persona_id)
    if before.level == level:
        return before
    row = state.projections[MEMBERS][str(persona_id)]
    if level == PopulationLevel.ACTIVE:
        lifecycle.activate(
            persona_id, active_state={}, world_step=world_step(row, now), reason=reason
        )
    elif level == PopulationLevel.MATERIALIZED:
        lifecycle.deactivate(
            persona_id,
            world_step=world_step(row, now),
            preserve_fields=MENTAL_FIELDS,
            reason=reason,
        )
    else:
        raise ValueError("bound members cannot return to the statistical pool")
    save_lifecycle(state, lifecycle, persona_id)
    return lifecycle.get(persona_id)


def projection_deltas(
    before: BranchState, after: BranchState, projections: tuple[str, ...]
) -> tuple[StateDelta, ...]:
    deltas = []
    for projection in projections:
        old, new = before.projections.get(projection, {}), after.projections.get(projection, {})
        for key in sorted(old.keys() | new.keys()):
            if old.get(key) != new.get(key):
                deltas.append(
                    StateDelta(
                        projection=projection,
                        entity_id=uuid.UUID(key),
                        operation="SET" if key in new else "DELETE",
                        values=new.get(key, {}),
                    )
                )
    return tuple(deltas)


class BindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    population_id: uuid.UUID
    entity_id: uuid.UUID
    source_member: PopulationMember


class LevelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: uuid.UUID
    expected_version: int = Field(ge=0)
    level: Literal["ACTIVE", "MATERIALIZED"]
    # Manual override persists until explicitly returned to AUTO.
    relevance: Literal["AUTO", "ACTIVE", "MATERIALIZED"] = "AUTO"


class MemberResult(BaseModel):
    persona_id: uuid.UUID
    entity_id: uuid.UUID
    version: int


def bind(proposal: CommandProposal, state: BranchState) -> CommandResult:
    from domains.tabletop.activities import seconds

    request = BindRequest.model_validate(proposal.parameters)
    member = request.source_member
    if (member.world_id, member.branch_id) != (state.world_id, state.branch_id):
        raise ValueError("population source belongs to another branch")
    if member.level == PopulationLevel.STATISTICAL or member.entity_id is not None:
        raise ValueError("materialize an unbound member before binding")
    if str(request.entity_id) not in state.projections.get("tabletop.entities", {}):
        raise ValueError("binding requires an existing canonical body")
    rows = state.projections.get(MEMBERS, {})
    if str(member.persona_id) in rows or any(
        row["entity_id"] == str(request.entity_id) for row in rows.values()
    ):
        raise ValueError("population identity and body must each be bound once")
    if len(rows) >= 256:
        raise ValueError("bound population limit reached")
    now = seconds(state)
    # Keep only cognition metadata, never a second inventory/balance/health store.
    clean = member.model_copy(
        update={
            field: {
                key: value for key, value in getattr(member, field).items() if key in MENTAL_FIELDS
            }
            for field in ("persistent_state", "active_state", "compressed_state")
        }
    )
    lifecycle = PopulationLifecycle(state.world_id, state.branch_id)
    lifecycle.restore([clean], [])
    embodied = lifecycle.embody(member.persona_id, request.entity_id, world_step=member.world_step)
    working = state.working_copy()
    working.projections.setdefault(MEMBERS, {})[str(member.persona_id)] = {
        "population_id": str(request.population_id),
        "entity_id": str(request.entity_id),
        "source_version": member.version,
        "source_hash": source_hash(member),
        "source_world_step": member.world_step,
        "bound_at_seconds": now,
        "relevance": "AUTO",
    }
    save_lifecycle(working, lifecycle, member.persona_id)
    return CommandResult(
        result={
            "persona_id": str(member.persona_id),
            "entity_id": str(request.entity_id),
            "version": embodied.version,
        },
        deltas=projection_deltas(state, working, (MEMBERS, HISTORY)),
        population_bindings=(
            PopulationBindingMutation(
                population_id=request.population_id,
                persona_id=member.persona_id,
                entity_id=request.entity_id,
                source_version=member.version,
                source_hash=source_hash(member),
            ),
        ),
        domain_tags=("operator", "population_binding"),
    )


def set_level(proposal: CommandProposal, state: BranchState) -> CommandResult:
    from domains.tabletop.activities import seconds

    request = LevelRequest.model_validate(proposal.parameters)
    lifecycle = lifecycle_for(state, request.persona_id)
    if lifecycle.get(request.persona_id).version != request.expected_version:
        raise ValueError("population lifecycle version changed")
    working = state.working_copy()
    member = transition(
        working,
        request.persona_id,
        PopulationLevel(request.level),
        seconds(state),
        "operator_relevance",
    )
    row = working.projections[MEMBERS][str(request.persona_id)]
    if member.version == request.expected_version and row["relevance"] != request.relevance:
        lifecycle = lifecycle_for(working, request.persona_id)
        member = lifecycle.record_relevance_override(
            request.persona_id, world_step=world_step(row, seconds(state))
        )
        save_lifecycle(working, lifecycle, request.persona_id)
    row["relevance"] = request.relevance
    return CommandResult(
        result={
            "persona_id": str(member.persona_id),
            "entity_id": str(member.entity_id),
            "version": member.version,
        },
        deltas=projection_deltas(state, working, (MEMBERS, HISTORY)),
        domain_tags=("operator", "population_lifecycle"),
    )


def validate_promoted_members(state: BranchState, deltas: tuple[StateDelta, ...]) -> None:
    """A trial may change a live lifecycle, but cannot invent or erase an import binding."""
    affected = [delta for delta in deltas if delta.projection == MEMBERS]
    if not affected:
        return
    working = state.working_copy()
    for delta in affected:
        working.apply(delta)
    old, new = state.projections.get(MEMBERS, {}), working.projections.get(MEMBERS, {})
    if old.keys() != new.keys():
        raise ValueError("promotion cannot add or remove population bindings")
    for key, row in old.items():
        immutable = {
            field: value for field, value in row.items() if field not in {"member", "relevance"}
        }
        candidate = new[key]
        if immutable != {
            field: value
            for field, value in candidate.items()
            if field not in {"member", "relevance"}
        }:
            raise ValueError("promotion cannot change population binding provenance")
        member = scoped_member(state, candidate["member"])
        if (str(member.persona_id), str(member.entity_id), member.profile) != (
            key,
            row["entity_id"],
            row["member"]["profile"],
        ):
            raise ValueError("promotion cannot change population identity or body")
        if member.level == PopulationLevel.STATISTICAL or candidate["relevance"] not in {
            "AUTO",
            "ACTIVE",
            "MATERIALIZED",
        }:
            raise ValueError("promotion requires a live population lifecycle")
        if any(
            set(getattr(member, field)) - MENTAL_FIELDS
            for field in ("persistent_state", "active_state", "compressed_state")
        ):
            raise ValueError("population resources belong to the canonical body")


def command_definitions() -> tuple[CommandDefinition, ...]:
    return (
        CommandDefinition(
            "tabletop.population.bind",
            frozenset({"action.propose", "entity.control"}),
            frozenset({BranchKind.CANONICAL}),
            bind,
            request_model=BindRequest,
            result_model=MemberResult,
            sensitive_parameters=frozenset({"source_member"}),
        ),
        CommandDefinition(
            "tabletop.population.level",
            frozenset({"action.propose", "entity.control"}),
            frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            set_level,
            request_model=LevelRequest,
            result_model=MemberResult,
        ),
    )
