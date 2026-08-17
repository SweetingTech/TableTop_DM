from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.state import BranchState


class DialogueClaim(BaseModel):
    subject_type: str = Field(min_length=1, max_length=120)
    subject_id: str | None = None
    predicate: str = Field(min_length=1, max_length=160)
    value: Any
    confidence: float = Field(default=1, ge=0, le=1)


class ConsoleSubmission(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    claims: tuple[DialogueClaim, ...] = ()


class ConsoleSubmissionResult(BaseModel):
    text: str
    submission_kind: Literal["COMMAND", "DIALOGUE"]
    interpreted: Literal[False]
    summary: str
    claims: tuple[DialogueClaim, ...] = ()


def submit(proposal: CommandProposal, state: BranchState) -> CommandResult:
    """Record player/GM speech or a slash-command proposal without interpreting prose."""
    request = ConsoleSubmission.model_validate(proposal.parameters)
    text = request.text.strip()
    if not text:
        raise ValueError("console text cannot be blank")
    is_command = text.startswith("/")
    result: dict[str, Any] = {
        "text": text,
        "submission_kind": "COMMAND" if is_command else "DIALOGUE",
        "interpreted": False,
        "summary": (f"Proposed {text}." if is_command else text),
    }
    if request.claims:
        result["claims"] = [claim.model_dump(mode="json") for claim in request.claims]
    return CommandResult(
        result=result,
        domain_tags=(
            "tabletop",
            "command" if is_command else "dialogue",
            "proposal",
        ),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.console.submit",
        required_capabilities=frozenset({"action.propose"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=submit,
        request_model=ConsoleSubmission,
        result_model=ConsoleSubmissionResult,
    )
