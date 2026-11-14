"""Contextual speech/combat preferences; no historical text or hidden targets are replayed."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cognition.choice_state import ChoiceFrame, choice_frame, speech_intent
from cognition.context import CharacterContext
from cognition.engine import DecisionAction
from kernel.state import stable_hash
from persona.models import CompiledPersona

CHOICE_VERSION = "speech-combat-behavior-1.1.0"


class ChoiceOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    kind: Literal["MOVE", "SPEECH", "ATTACK", "GUARD", "SPELL"]
    style: str
    volume: str = ""


def option_key(command_type: str, parameters: dict) -> str:
    if command_type == "tabletop.combat.guard":
        return "guard"
    if command_type == "tabletop.magic.invoke":
        return f"spell:{parameters.get('spell_id')}:{parameters.get('target_id')}"
    if command_type == "tabletop.spatial.move":
        return f"move:{parameters.get('dx')},{parameters.get('dy')}"
    if command_type == "tabletop.combat.attack":
        return "attack:" + str(parameters.get("target_id"))
    if (
        command_type == "tabletop.dialogue.speak"
        and parameters.get("language", "common") == "common"
    ):
        return (
            "speech:"
            + speech_intent(str(parameters.get("text", "")))
            + ":"
            + str(parameters.get("volume", "NORMAL"))
        )
    return ""


def describe_options(context: CharacterContext, frame: ChoiceFrame) -> tuple[ChoiceOption, ...]:
    body = next(
        row
        for row in context.scene.perceived_entities
        if row.entity_id == context.scene.observer_entity_id
    )
    positions = {
        row.entity_id: row.position
        for row in context.scene.perceived_entities
        if row.position is not None
    }
    here = body.position
    result = []
    nearest = min((row.distance for row in frame.threats), default=0)
    for action in context.actions:
        key = option_key(action.command_type, action.parameters)
        if not key:
            continue
        if key.startswith("speech:"):
            result.append(
                ChoiceOption(
                    key=key,
                    kind="SPEECH",
                    style=speech_intent(action.parameters["text"]),
                    volume=action.parameters.get("volume", "NORMAL"),
                )
            )
        elif key == "guard":
            result.append(ChoiceOption(key=key, kind="GUARD", style="DEFEND"))
        elif key.startswith("spell:MEND:"):
            result.append(ChoiceOption(key=key, kind="SPELL", style="HEAL_SELF"))
        elif key.startswith("attack:") or key.startswith("spell:ARCANE_BOLT:"):
            target = next(
                (
                    row
                    for row in frame.threats
                    if str(row.entity_id) == str(action.parameters["target_id"])
                ),
                None,
            )
            if target is not None:
                result.append(
                    ChoiceOption(
                        key=key,
                        kind="ATTACK" if key.startswith("attack:") else "SPELL",
                        style="WOUNDED"
                        if target.wounded
                        else "NEAREST"
                        if target.distance == nearest
                        else "OTHER",
                    )
                )
        elif here is not None:
            dx, dy = action.parameters["dx"], action.parameters["dy"]
            distances = [
                max(
                    abs(positions[row.entity_id].x - here.x - dx),
                    abs(positions[row.entity_id].y - here.y - dy),
                )
                for row in frame.threats
            ]
            after = min(distances, default=nearest)
            style = "RETREAT" if after > nearest else "ADVANCE" if after < nearest else "MANEUVER"
            result.append(ChoiceOption(key=key, kind="MOVE", style=style))
    return tuple(result)


class HumanChoiceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["speech-combat-behavior-1.0.0", "speech-combat-behavior-1.1.0"] = (
        "speech-combat-behavior-1.1.0"
    )
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    player_actor_id: uuid.UUID
    character_id: uuid.UUID
    binding_id: uuid.UUID
    projection_version: int = Field(ge=0)
    frame: ChoiceFrame
    options: tuple[ChoiceOption, ...]
    chosen_key: str

    @model_validator(mode="after")
    def selected_option(self) -> HumanChoiceEvidence:
        if self.version == "speech-combat-behavior-1.0.0" and any(
            row.kind in {"GUARD", "SPELL"} for row in self.options
        ):
            raise ValueError("tactical options require the current evidence version")
        if self.chosen_key not in {row.key for row in self.options}:
            raise ValueError("human choice is absent from perceived options")
        return self


class ChoiceProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_id: str
    version: str = CHOICE_VERSION
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    player_actor_id: uuid.UUID
    character_id: uuid.UUID
    binding_id: uuid.UUID
    context_hash: str
    persona_version: str
    active: bool
    comparable_count: int = Field(ge=0, le=256)
    confidence: float = Field(ge=0, le=1)
    evidence_event_ids: tuple[uuid.UUID, ...]
    action_scores: dict[str, float]
    conflicts: tuple[str, ...]

    @model_validator(mode="after")
    def content_address(self) -> ChoiceProfile:
        if self.profile_id != stable_hash(self.model_dump(mode="json", exclude={"profile_id"})):
            raise ValueError("choice profile version differs from its content")
        return self


def choice_profile(
    context: CharacterContext,
    persona: CompiledPersona,
    *,
    run_id: uuid.UUID,
    player_actor_id: uuid.UUID,
    character_id: uuid.UUID,
    binding_id: uuid.UUID,
    evidence: tuple[tuple[uuid.UUID, HumanChoiceEvidence], ...],
) -> ChoiceProfile:
    frame = choice_frame(context.scene, context.observations)
    options = describe_options(context, frame) if frame else ()
    scope = (
        context.scene.world_id,
        context.scene.branch_id,
        run_id,
        context.scene.observer_entity_id,
        player_actor_id,
        character_id,
    )
    matching = sorted(
        (
            (event, row)
            for event, row in evidence
            if frame
            and row.frame.signature == frame.signature
            and (
                row.world_id,
                row.branch_id,
                row.run_id,
                row.entity_id,
                row.player_actor_id,
                row.character_id,
            )
            == scope
        ),
        key=lambda row: str(row[0]),
    )
    choices = [
        next(option for option in row.options if option.key == row.chosen_key)
        for _, row in matching
    ]
    confidence = len(matching) / (len(matching) + 3)
    identity = context.identity.authored_identity if context.identity else None
    text = (
        " ".join((identity.backstory, *identity.motives, *identity.values)).lower()
        if identity
        else ""
    )
    peaceful = any(word in text for word in ("pacifist", "peaceful", "mercy", "avoid violence"))
    aggressive = any(word in text for word in ("aggressive", "vengeful", "warrior", "bold"))
    levels = {"LOW": 0.25, "MEDIUM": 0.55, "HIGH": 0.85}
    risk = levels.get(str(persona.deep_traits.get("risk_tolerance")), 0.55)
    social = levels.get(str(persona.deep_traits.get("extraversion")), 0.55)
    direct = persona.deep_traits.get("communication_directness") == "DIRECT"
    avoid = persona.deep_traits.get("conflict_style") == "AVOID"
    battle = bool(frame and frame.threats)
    scores = {}
    for option in options:
        if option.kind == "GUARD":
            base = 0.8 + (1 if frame and frame.spatial.injured else 0) + (0.6 if avoid else 0)
        elif option.kind == "SPELL" and option.style == "HEAL_SELF":
            base = 3.5 if frame and frame.spatial.injured else 0.5
        elif option.kind in {"ATTACK", "SPELL"}:
            base = (
                1
                + (risk - 0.55) * 2
                + (0.8 if aggressive else 0)
                - (1.8 if peaceful or avoid else 0)
            )
            if option.style == "WOUNDED":
                base += 0.25
            if option.kind == "SPELL":
                base += 0.25 if frame and min(row.distance for row in frame.threats) > 1 else -0.2
        elif option.kind == "MOVE":
            base = (
                (1.5 if frame and frame.spatial.injured else 0.4) + (0.55 - risk) * 2
                if option.style == "RETREAT" and battle
                else 0.6
                if battle and option.style == "ADVANCE" and aggressive
                else 0.1
            )
        else:
            if battle:
                base = {
                    "DEESCALATE": 1.8 if peaceful or avoid else 0.25,
                    "ASSERT": 0.4,
                    "GREET": -1.0,
                    "ASK": -0.5,
                }[option.style]
            else:
                base = {
                    "GREET": 0.5 + social,
                    "ASK": 0.5 + persona.policy_weights.get("curiosity", 0.55),
                    "DEESCALATE": 0.1,
                    "ASSERT": -0.6,
                }[option.style]
            base += (
                0.3
                if option.volume == "NORMAL"
                else 0.1
                if option.volume == "WHISPER"
                else -0.35
                if option.volume == "LOUD"
                else -0.65
            )
            if direct and option.style == "ASSERT":
                base += 0.5
        count = sum(
            (row.kind, row.style, row.volume) == (option.kind, option.style, option.volume)
            for row in choices
        )
        scores[option.key] = round(
            base * (1 - confidence) + 6 * confidence * count / max(1, len(choices)), 6
        )
    conflicts: tuple[str, ...] = ()
    if peaceful and sum(row.kind == "ATTACK" for row in choices) >= 3:
        conflicts = (
            "Repeated human attacks conflict with the pinned peaceful tendency; "
            "review the card or history.",
        )
    payload = dict(
        version=CHOICE_VERSION,
        world_id=scope[0],
        branch_id=scope[1],
        run_id=run_id,
        entity_id=scope[3],
        player_actor_id=player_actor_id,
        character_id=character_id,
        binding_id=binding_id,
        context_hash=context.evidence_hash,
        persona_version=persona.persona_version,
        active=bool(frame and (frame.threats or frame.speech_ready)),
        comparable_count=len(matching),
        confidence=confidence,
        evidence_event_ids=tuple(event for event, _ in matching),
        action_scores=scores,
        conflicts=conflicts,
    )
    return ChoiceProfile(profile_id=stable_hash(payload), **payload)


def weighted_choices(
    actions: tuple[DecisionAction, ...], profile: ChoiceProfile | None
) -> tuple[DecisionAction, ...]:
    if profile is None or not profile.active:
        return actions
    return tuple(
        action.model_copy(
            update={
                "utility_factors": {
                    **{
                        key: value
                        for key, value in action.utility_factors.items()
                        if key != "behavior"
                    },
                    "choice_behavior": profile.action_scores.get(
                        option_key(action.command_type, action.parameters), 0
                    ),
                }
            }
        )
        for action in actions
    )
