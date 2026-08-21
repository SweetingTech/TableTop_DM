from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState

from .models import SpatialPosition

__all__ = [
    "Coordinate",
    "MoveRequest",
    "MoveResult",
    "SpatialPosition",
    "command_definition",
    "move",
]


class MoveRequest(BaseModel):
    dx: int = Field(ge=-1, le=1)
    dy: int = Field(ge=-1, le=1)


class Coordinate(BaseModel):
    x: int
    y: int


class MoveResult(BaseModel):
    entity_id: uuid.UUID
    origin: Coordinate
    destination: Coordinate
    zone_id: uuid.UUID | str


def move(proposal: CommandProposal, state: BranchState) -> CommandResult:
    entity_id = proposal.embodied_entity_id
    if entity_id is None:
        raise ValueError("movement requires an embodied entity")
    request = MoveRequest.model_validate(proposal.parameters)
    if request.dx == 0 and request.dy == 0:
        raise ValueError("movement must change at least one coordinate")
    entities = state.projections.get("tabletop.entities", {})
    explicit = state.projections.get("tabletop.spatial.positions", {})
    current = explicit.get(str(entity_id), entities.get(str(entity_id)))
    if current is None:
        raise ValueError("embodied entity does not exist")
    destination = {
        "x": int(current.get("x", 0)) + request.dx,
        "y": int(current.get("y", 0)) + request.dy,
    }
    blocked = {
        (int(value["x"]), int(value["y"]))
        for value in state.projections.get("tabletop.obstacles", {}).values()
    }
    if (destination["x"], destination["y"]) in blocked:
        raise ValueError("destination is blocked")
    return CommandResult(
        result={
            "entity_id": str(entity_id),
            "origin": {"x": int(current.get("x", 0)), "y": int(current.get("y", 0))},
            "destination": destination,
            "zone_id": current.get("zone_id", "world"),
        },
        deltas=(
            StateDelta(
                projection="tabletop.spatial.positions",
                operation="SET",
                entity_id=entity_id,
                values=SpatialPosition(
                    entity_id=entity_id,
                    zone_id=current.get("zone_id", "world"),
                    x=destination["x"],
                    y=destination["y"],
                    z=int(current.get("z", 0)),
                    facing=current.get("facing"),
                ).model_dump(mode="json", exclude={"entity_id"}),
            ),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=entity_id,
                values=destination,
            ),
        ),
        domain_tags=("tabletop", "spatial", "movement"),
    )


def movement_emission(
    proposal: CommandProposal,
    result: CommandResult,
    before: BranchState,
    after: BranchState,
) -> EventEmission:
    del result, before, after
    if proposal.embodied_entity_id is None:
        raise ValueError("movement emission requires an embodied entity")
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="BEFORE"),
        modalities=(SensoryModality.SIGHT,),
        max_range=12,
        allowed_payload_fields=("entity_id", "origin", "destination", "zone_id"),
        reason_codes=("movement.visible_transition",),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.spatial.move",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=move,
        request_model=MoveRequest,
        result_model=MoveResult,
        requires_controlled_entity=True,
        emission_builder=movement_emission,
    )
