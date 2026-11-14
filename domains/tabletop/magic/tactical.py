"""Fixed spell presets: callers choose intent/target, never power, cost or range."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState

SPELLS = {"ARCANE_BOLT": ("DAMAGE", 3, 2, 6), "MEND": ("HEAL", 4, 2, 2)}


class StartingResources(BaseModel):
    mana: int = Field(default=0, ge=0)


class InvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spell_id: Literal["ARCANE_BOLT", "MEND"]
    target_id: uuid.UUID


class InvokeResult(BaseModel):
    caster_id: uuid.UUID
    target_id: uuid.UUID
    spell_id: str
    effect: str
    power: int
    mana_after: int


def invoke(proposal: CommandProposal, state: BranchState) -> CommandResult:
    if proposal.embodied_entity_id is None:
        raise ValueError("an embodied caster is required")
    request = InvokeRequest.model_validate(proposal.parameters)
    effect, power, cost, reach = SPELLS[request.spell_id]
    bodies = state.projections.get("tabletop.entities", {})
    caster, target = (
        bodies.get(str(proposal.embodied_entity_id)),
        bodies.get(str(request.target_id)),
    )
    if (
        caster is None
        or target is None
        or min(int(caster.get("hp", 0)), int(target.get("hp", 0))) <= 0
    ):
        raise ValueError("capable caster and target are required")
    if effect == "DAMAGE" and request.target_id == proposal.embodied_entity_id:
        raise ValueError("damaging invocation requires another target")
    if int(caster.get("mana", 0)) < cost:
        raise ValueError("insufficient mana")
    positions = state.projections.get("tabletop.spatial.positions", {})
    origin, destination = (
        positions.get(str(proposal.embodied_entity_id), caster),
        positions.get(str(request.target_id), target),
    )
    if (
        origin.get("zone_id", "world") != destination.get("zone_id", "world")
        or max(abs(int(origin.get(axis, 0)) - int(destination.get(axis, 0))) for axis in ("x", "y"))
        > reach
        or request.target_id
        not in GridSpatialPerceptionResolver().visible_entities(state, proposal.embodied_entity_id)
    ):
        raise ValueError("target is not in visible spell reach")
    health = int(target.get("hp", 0))
    after = (
        max(0, health - power)
        if effect == "DAMAGE"
        else min(int(target.get("max_hp", health)), health + power)
    )
    if effect == "HEAL" and after == health:
        raise ValueError("target does not need healing")
    return CommandResult(
        result={
            "caster_id": str(proposal.embodied_entity_id),
            "target_id": str(request.target_id),
            "spell_id": request.spell_id,
            "effect": effect,
            "power": power,
            "mana_after": int(caster.get("mana", 0)) - cost,
        },
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=proposal.embodied_entity_id,
                values={"mana": int(caster.get("mana", 0)) - cost},
            ),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.target_id,
                values={"hp": after, "defeated": after <= 0},
            ),
        ),
        domain_tags=("tabletop", "magic", "invocation"),
    )


def invoke_emission(proposal, result, before, after):
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id),
        modalities=(SensoryModality.SIGHT, SensoryModality.SOUND),
        max_range=12,
        allowed_payload_fields=("caster_id", "target_id", "spell_id", "effect", "power"),
        reason_codes=("magic.invocation",),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.magic.invoke",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=invoke,
        request_model=InvokeRequest,
        result_model=InvokeResult,
        requires_controlled_entity=True,
        emission_builder=invoke_emission,
    )
