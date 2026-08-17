from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState, InMemoryStateStore


class ConsequencePackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_branch_id: uuid.UUID
    expected_canonical_hash: str
    deltas: tuple[StateDelta, ...] = Field(min_length=1)
    review_note: str = Field(min_length=1, max_length=2_000)


class PromotionResult(BaseModel):
    source_branch_id: uuid.UUID
    promoted_delta_count: int = Field(ge=1)
    review_note: str


def promote_consequences(proposal: CommandProposal, state: BranchState) -> CommandResult:
    package = ConsequencePackage.model_validate(proposal.parameters)
    if state.kind is not BranchKind.CANONICAL:
        raise ValueError("consequences can only be promoted to canonical branches")
    if state.state_hash != package.expected_canonical_hash:
        raise ValueError("canonical state changed after the trial snapshot")
    return CommandResult(
        result={
            "source_branch_id": str(package.source_branch_id),
            "promoted_delta_count": len(package.deltas),
            "review_note": package.review_note,
        },
        deltas=package.deltas,
        domain_tags=("kernel", "branch", "canonical_promotion"),
    )


def promotion_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="kernel.branch.promote",
        required_capabilities=frozenset({"canonical.promote", "action.commit"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
        handler=promote_consequences,
        request_model=ConsequencePackage,
        result_model=PromotionResult,
    )


class BranchManager:
    def __init__(self, states: InMemoryStateStore) -> None:
        self.states = states

    def create_world(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        projections: dict | None = None,
    ) -> BranchState:
        canonical = BranchState(
            world_id=world_id,
            branch_id=branch_id,
            kind=BranchKind.CANONICAL,
            projections=projections or {},
        )
        self.states.add(canonical)
        return canonical

    def branch_trial(
        self, canonical_branch_id: uuid.UUID, trial_branch_id: uuid.UUID
    ) -> BranchState:
        return self.states.create_trial(canonical_branch_id, trial_branch_id)
