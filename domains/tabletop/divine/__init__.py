from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState


class BlessRequest(BaseModel):
    target_id: uuid.UUID
    blessing: str = Field(min_length=1, max_length=100)
    duration_turns: int = Field(default=1, ge=1, le=10_000)


class BlessResult(BaseModel):
    target_id: uuid.UUID
    blessing: str
    duration_turns: int = Field(ge=1)


def bless(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = BlessRequest.model_validate(proposal.parameters)
    target = state.projections.get("tabletop.entities", {}).get(str(request.target_id))
    if target is None:
        raise ValueError("blessing target does not exist")
    blessings = list(target.get("blessings", []))
    blessings.append({"name": request.blessing, "remaining_turns": request.duration_turns})
    return CommandResult(
        result={
            "target_id": str(request.target_id),
            "blessing": request.blessing,
            "duration_turns": request.duration_turns,
        },
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.target_id,
                values={"blessings": blessings},
            ),
        ),
        domain_tags=("tabletop", "divine", "blessing"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.divine.bless",
        required_capabilities=frozenset({"divine.invoke"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=bless,
        request_model=BlessRequest,
        result_model=BlessResult,
    )
