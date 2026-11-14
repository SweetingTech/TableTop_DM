"""Universal, server-owned defensive action; no class or protagonist restrictions."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState


class GuardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GuardResult(BaseModel):
    entity_id: uuid.UUID
    guarded: bool


def guard(proposal: CommandProposal, state: BranchState) -> CommandResult:
    body = state.projections.get("tabletop.entities", {}).get(str(proposal.embodied_entity_id))
    if body is None or int(body.get("hp", 0)) <= 0 or body.get("guarded"):
        raise ValueError("a capable unguarded body is required")
    return CommandResult(
        result={"entity_id": str(proposal.embodied_entity_id), "guarded": True},
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=proposal.embodied_entity_id,
                values={"guarded": True},
            ),
        ),
        domain_tags=("tabletop", "combat", "guard"),
    )


def guard_emission(proposal, result, before, after):
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id),
        modalities=(SensoryModality.SIGHT,),
        max_range=8,
        allowed_payload_fields=("entity_id", "guarded"),
        reason_codes=("combat.guard",),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.combat.guard",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=guard,
        request_model=GuardRequest,
        result_model=GuardResult,
        requires_controlled_entity=True,
        emission_builder=guard_emission,
    )
