from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState


class MoveRequest(BaseModel):
    dx: int = Field(ge=-1, le=1)
    dy: int = Field(ge=-1, le=1)


class Coordinate(BaseModel):
    x: int
    y: int


class MoveResult(BaseModel):
    entity_id: uuid.UUID
    destination: Coordinate


def move(proposal: CommandProposal, state: BranchState) -> CommandResult:
    entity_id = proposal.embodied_entity_id
    if entity_id is None:
        raise ValueError("movement requires an embodied entity")
    request = MoveRequest.model_validate(proposal.parameters)
    if request.dx == 0 and request.dy == 0:
        raise ValueError("movement must change at least one coordinate")
    entities = state.projections.get("tabletop.entities", {})
    current = entities.get(str(entity_id))
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
        result={"entity_id": str(entity_id), "destination": destination},
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=entity_id,
                values=destination,
            ),
        ),
        domain_tags=("tabletop", "spatial", "movement"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.spatial.move",
        required_capabilities=frozenset({"action.propose", "entity.control"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=move,
        request_model=MoveRequest,
        result_model=MoveResult,
    )
