from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

ONBOARDING_STEPS = (
    "WELCOME",
    "LEARN_CONTROLS",
    "COMPLETE_TASK",
    "CLAIM_REWARD",
    "CHOOSE_PATH",
    "FINISH",
)

EXPECTED_ACTION = {
    "WELCOME": "START",
    "LEARN_CONTROLS": "READ_INSTRUCTIONS",
    "COMPLETE_TASK": "COMPLETE_FIRST_GOAL",
    "CLAIM_REWARD": "CLAIM_REWARD",
    "CHOOSE_PATH": "CHOOSE_PATH",
    "FINISH": "FINISH_ONBOARDING",
}


class OnboardingAction(BaseModel):
    action: str


class OnboardingResult(BaseModel):
    action: str
    expected_action: str
    step: str
    outcome: Literal["INVALID", "ALREADY_COMPLETE", "HELP_PROVIDED", "VALID"]


def handle_onboarding_action(proposal: CommandProposal, state: BranchState) -> CommandResult:
    if proposal.embodied_entity_id is None:
        raise ValueError("onboarding actions require an embodied entity")
    key = str(proposal.embodied_entity_id)
    record = state.projections.get("tabletop.onboarding", {}).get(key)
    if record is None:
        record = {
            "step_index": 0,
            "invalid_actions": 0,
            "help_requests": 0,
            "hints_requested": 0,
            "dialogue_loops": 0,
            "completed": False,
            "had_help_this_step": False,
        }
    action = str(proposal.parameters.get("action", ""))
    step_index = int(record["step_index"])
    step = ONBOARDING_STEPS[min(step_index, len(ONBOARDING_STEPS) - 1)]
    expected = EXPECTED_ACTION[step]
    changes: dict[str, object] = {}
    outcome = "INVALID"
    if record["completed"]:
        outcome = "ALREADY_COMPLETE"
    elif action == "ASK_HELP":
        changes = {
            "help_requests": int(record["help_requests"]) + 1,
            "hints_requested": int(record["hints_requested"])
            + (1 if step == "COMPLETE_TASK" else 0),
            "dialogue_loops": int(record["dialogue_loops"])
            + (1 if record["had_help_this_step"] else 0),
            "had_help_this_step": True,
        }
        outcome = "HELP_PROVIDED"
    elif action == expected:
        next_index = step_index + 1
        changes = {
            "step_index": next_index,
            "had_help_this_step": False,
            "completed": next_index >= len(ONBOARDING_STEPS),
        }
        outcome = "VALID"
    else:
        changes = {"invalid_actions": int(record["invalid_actions"]) + 1}

    next_record = dict(record)
    next_record.update(changes)
    return CommandResult(
        result={
            "action": action,
            "expected_action": expected,
            "step": step,
            "outcome": outcome,
        },
        deltas=(
            StateDelta(
                projection="tabletop.onboarding",
                operation="SET",
                entity_id=proposal.embodied_entity_id,
                values=next_record,
            ),
        ),
        domain_tags=("tabletop", "onboarding"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.onboarding.act",
        required_capabilities=frozenset({"action.propose", "entity.control"}),
        allowed_branch_kinds=frozenset({BranchKind.TRIAL, BranchKind.CANONICAL}),
        handler=handle_onboarding_action,
        request_model=OnboardingAction,
        result_model=OnboardingResult,
    )
