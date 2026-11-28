from __future__ import annotations

import uuid

from pydantic import Field

from kernel.campaign_checkpoints import CheckpointModel, Digest
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.state import BranchState

ACTIVATE_CAMPAIGN_REVISION = "kernel.campaign.activate_revision"


class CampaignActivationFacts(CheckpointModel):
    source_branch_id: uuid.UUID
    source_checkpoint_id: uuid.UUID
    request_id: uuid.UUID
    epoch: int = Field(ge=1)
    state_hash: Digest


def activate_campaign_revision(proposal: CommandProposal, state: BranchState) -> CommandResult:
    facts = CampaignActivationFacts.model_validate(proposal.parameters)
    if facts.source_branch_id == state.branch_id or facts.state_hash != state.state_hash:
        raise ValueError("activation requires the restored successor projection")
    return CommandResult(
        result=facts.model_dump(mode="json"),
        domain_tags=("kernel", "operator", "timeline_revision"),
    )


def campaign_activation_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type=ACTIVATE_CAMPAIGN_REVISION,
        required_capabilities=frozenset({"action.commit", "entity.control", "mind.write.all"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
        handler=activate_campaign_revision,
        request_model=CampaignActivationFacts,
        result_model=CampaignActivationFacts,
    )
