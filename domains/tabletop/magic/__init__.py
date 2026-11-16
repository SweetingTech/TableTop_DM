"""The legacy cast entry point shares the authoritative invocation rules."""

from __future__ import annotations

from domains.tabletop.magic.tactical import InvokeRequest, InvokeResult, invoke, invoke_emission
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.state import BranchState

CastRequest = InvokeRequest
CastResult = InvokeResult


def cast(proposal: CommandProposal, state: BranchState) -> CommandResult:
    return invoke(proposal, state)


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.magic.cast",
        version="2.1.0",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=cast,
        request_model=CastRequest,
        result_model=CastResult,
        requires_controlled_entity=True,
        emission_builder=invoke_emission,
        uses_randomness=True,
    )
