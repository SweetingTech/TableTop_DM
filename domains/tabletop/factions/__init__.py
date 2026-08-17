from __future__ import annotations

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState


class ReputationRequest(BaseModel):
    faction_id: str = Field(min_length=1, max_length=120)
    amount: int = Field(ge=-100, le=100)
    reason: str = Field(min_length=1, max_length=240)


class ReputationResult(BaseModel):
    faction_id: str
    before: int = Field(ge=-100, le=100)
    after: int = Field(ge=-100, le=100)
    reason: str


def adjust_reputation(proposal: CommandProposal, state: BranchState) -> CommandResult:
    entity_id = proposal.embodied_entity_id
    if entity_id is None:
        raise ValueError("reputation requires an embodied entity")
    request = ReputationRequest.model_validate(proposal.parameters)
    record = state.projections.get("tabletop.reputation", {}).get(str(entity_id), {})
    values = dict(record.get("factions", {}))
    before = int(values.get(request.faction_id, 0))
    after = max(-100, min(100, before + request.amount))
    values[request.faction_id] = after
    return CommandResult(
        result={
            "faction_id": request.faction_id,
            "before": before,
            "after": after,
            "reason": request.reason,
        },
        deltas=(
            StateDelta(
                projection="tabletop.reputation",
                operation="MERGE",
                entity_id=entity_id,
                values={"factions": values},
            ),
        ),
        domain_tags=("tabletop", "faction", request.faction_id),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.faction.adjust_reputation",
        required_capabilities=frozenset({"faction.manage"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=adjust_reputation,
        request_model=ReputationRequest,
        result_model=ReputationResult,
    )
