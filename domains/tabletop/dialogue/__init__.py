from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
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


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4_000)
    volume: Literal["WHISPER", "NORMAL", "LOUD", "SHOUT"] = "NORMAL"
    language: str = Field(default="common", min_length=1, max_length=80)
    claims: tuple[DialogueClaim, ...] = ()


class SpeechResult(BaseModel):
    speaker_entity_id: uuid.UUID
    text: str
    volume: Literal["WHISPER", "NORMAL", "LOUD", "SHOUT"]
    language: str
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


def speak(proposal: CommandProposal, state: BranchState) -> CommandResult:
    del state
    if proposal.embodied_entity_id is None:
        raise ValueError("in-world speech requires an embodied entity")
    request = SpeechRequest.model_validate(proposal.parameters)
    text = request.text.strip()
    if not text:
        raise ValueError("speech cannot be blank")
    return CommandResult(
        result={
            "speaker_entity_id": str(proposal.embodied_entity_id),
            "text": text,
            "volume": request.volume,
            "language": request.language,
            "summary": text,
            "claims": [claim.model_dump(mode="json") for claim in request.claims],
        },
        domain_tags=("tabletop", "dialogue", "speech", "testimony"),
    )


_SPEECH_RANGE = {"WHISPER": 1.5, "NORMAL": 8.0, "LOUD": 16.0, "SHOUT": 32.0}
_SPEECH_INTENSITY = {"WHISPER": 0.8, "NORMAL": 1.0, "LOUD": 1.35, "SHOUT": 2.0}


def speech_emission(
    proposal: CommandProposal,
    result: CommandResult,
    before: BranchState,
    after: BranchState,
) -> EventEmission:
    del before, after
    if proposal.embodied_entity_id is None:
        raise ValueError("speech emission requires an embodied entity")
    volume = str(result.result["volume"])
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="BEFORE"),
        modalities=(SensoryModality.SOUND,),
        intensity=_SPEECH_INTENSITY[volume],
        max_range=_SPEECH_RANGE[volume],
        allowed_payload_fields=(
            "speaker_entity_id",
            "text",
            "volume",
            "language",
            "summary",
            "claims",
        ),
        reason_codes=(f"speech.volume.{volume.lower()}",),
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    branches = frozenset({BranchKind.CANONICAL, BranchKind.TRIAL})
    return (
        CommandDefinition(
            command_type="tabletop.console.submit",
            required_capabilities=frozenset({"action.propose"}),
            allowed_branch_kinds=branches,
            handler=submit,
            request_model=ConsoleSubmission,
            result_model=ConsoleSubmissionResult,
        ),
        CommandDefinition(
            command_type="tabletop.dialogue.speak",
            required_capabilities=frozenset({"action.propose", "entity.act"}),
            allowed_branch_kinds=branches,
            handler=speak,
            request_model=SpeechRequest,
            result_model=SpeechResult,
            requires_controlled_entity=True,
            emission_builder=speech_emission,
        ),
    )
