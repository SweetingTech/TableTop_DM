from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState


class CastRequest(BaseModel):
    target_id: uuid.UUID
    spell: str = Field(min_length=1, max_length=80)
    mana_cost: int = Field(ge=0, le=1_000)
    effect: Literal["DAMAGE", "HEAL", "CONDITION"]
    power: int = Field(default=0, ge=0, le=10_000)
    condition: str | None = Field(default=None, max_length=80)


class CastResult(BaseModel):
    spell: str
    caster_id: uuid.UUID
    target_id: uuid.UUID
    effect: Literal["DAMAGE", "HEAL", "CONDITION"]
    power: int = Field(ge=0)
    mana_after: int = Field(ge=0)


def cast(proposal: CommandProposal, state: BranchState) -> CommandResult:
    caster_id = proposal.embodied_entity_id
    if caster_id is None:
        raise ValueError("spellcasting requires an embodied entity")
    request = CastRequest.model_validate(proposal.parameters)
    entities = state.projections.get("tabletop.entities", {})
    caster = entities.get(str(caster_id))
    target = entities.get(str(request.target_id))
    if caster is None or target is None:
        raise ValueError("caster and target must exist")
    mana_before = int(caster.get("mana", 0))
    if mana_before < request.mana_cost:
        raise ValueError("insufficient mana")
    target_changes: dict[str, object] = {}
    if request.effect == "DAMAGE":
        target_changes["hp"] = max(0, int(target.get("hp", 0)) - request.power)
    elif request.effect == "HEAL":
        target_changes["hp"] = min(
            int(target.get("max_hp", target.get("hp", 0))),
            int(target.get("hp", 0)) + request.power,
        )
    else:
        if not request.condition:
            raise ValueError("condition effects require a condition")
        conditions = list(target.get("conditions", []))
        if request.condition not in conditions:
            conditions.append(request.condition)
        target_changes["conditions"] = conditions
    return CommandResult(
        result={
            "spell": request.spell,
            "caster_id": str(caster_id),
            "target_id": str(request.target_id),
            "effect": request.effect,
            "power": request.power,
            "mana_after": mana_before - request.mana_cost,
        },
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=caster_id,
                values={"mana": mana_before - request.mana_cost},
            ),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.target_id,
                values=target_changes,
            ),
        ),
        domain_tags=("tabletop", "magic", request.spell.lower().replace(" ", "_")),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.magic.cast",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=cast,
        request_model=CastRequest,
        result_model=CastResult,
        requires_controlled_entity=True,
    )
