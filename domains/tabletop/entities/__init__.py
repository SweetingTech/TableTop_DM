from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import (
    BranchKind,
    CommandProposal,
    CommandResult,
    EntityMutation,
    StateDelta,
)
from kernel.state import BranchState


class SpawnEntityRequest(BaseModel):
    entity_id: uuid.UUID
    name: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(min_length=1, max_length=120)
    public_state: dict[str, Any] = Field(default_factory=dict)
    secret_state: dict[str, Any] = Field(default_factory=dict)
    controller_actor_id: uuid.UUID | None = None


class SpawnEntityResult(BaseModel):
    entity_id: uuid.UUID
    name: str
    entity_type: str
    public_state: dict[str, Any]


def spawn(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = SpawnEntityRequest.model_validate(proposal.parameters)
    entities = state.projections.get("tabletop.entities", {})
    if str(request.entity_id) in entities:
        raise ValueError("entity already exists in this branch")
    values = {
        "name": request.name,
        "entity_type": request.entity_type,
        **request.public_state,
    }
    position = {
        "entity_id": str(request.entity_id),
        "zone_id": request.public_state.get("zone_id", "world"),
        "x": int(request.public_state.get("x", 0)),
        "y": int(request.public_state.get("y", 0)),
        "z": int(request.public_state.get("z", 0)),
        "facing": request.public_state.get("facing"),
    }
    sensory_profile = {
        "controller_actor_id": (
            str(request.controller_actor_id) if request.controller_actor_id else None
        ),
        "hearing_acuity": float(request.public_state.get("hearing_acuity", 1.0)),
        "sight_acuity": float(request.public_state.get("sight_acuity", 1.0)),
        "deafened": bool(request.public_state.get("deafened", False)),
        "blinded": bool(request.public_state.get("blinded", False)),
        "invisible": bool(request.public_state.get("invisible", False)),
    }
    return CommandResult(
        result={
            "entity_id": str(request.entity_id),
            "name": request.name,
            "entity_type": request.entity_type,
            "public_state": request.public_state,
        },
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="SET",
                entity_id=request.entity_id,
                values=values,
            ),
            StateDelta(
                projection="tabletop.spatial.positions",
                operation="SET",
                entity_id=request.entity_id,
                values=position,
            ),
            StateDelta(
                projection="tabletop.sensory_profiles",
                operation="SET",
                entity_id=request.entity_id,
                values=sensory_profile,
            ),
        ),
        entity_mutations=(
            EntityMutation(
                entity_id=request.entity_id,
                entity_type=request.entity_type,
                name=request.name,
                public_state=request.public_state,
                secret_state=request.secret_state,
                controller_actor_id=request.controller_actor_id,
            ),
        ),
        domain_tags=("tabletop", "entity", "spawn"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.entity.spawn",
        required_capabilities=frozenset({"entity.create", "entity.control"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=spawn,
        request_model=SpawnEntityRequest,
        result_model=SpawnEntityResult,
        sensitive_parameters=frozenset({"secret_state"}),
    )
