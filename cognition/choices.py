"""Contextual speech/combat preferences; no historical text or hidden targets are replayed."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cognition.choice_state import ChoiceFrame, SpeechCadence, choice_frame, speech_intent
from cognition.context import CharacterContext
from cognition.engine import DecisionAction
from kernel.state import stable_hash
from persona.models import CompiledPersona

CHOICE_VERSION = "speech-combat-behavior-1.4.0"
SUPPORT_EVIDENCE_VERSION = "speech-combat-behavior-1.3.0"


class ChoiceOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    kind: Literal["MOVE", "SPEECH", "ATTACK", "GUARD", "SPELL"]
    style: str
    volume: str = ""

    @property
    def category(self) -> tuple[str, str, str]:
        return (self.kind, self.style, self.volume)


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
            style = (
                "HEAL_SELF"
                if str(action.parameters["target_id"]) == str(body.entity_id)
                else "HEAL_HELPER"
            )
            result.append(ChoiceOption(key=key, kind="SPELL", style=style))
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
    version: Literal[
        "speech-combat-behavior-1.0.0",
        "speech-combat-behavior-1.1.0",
        "speech-combat-behavior-1.2.0",
        "speech-combat-behavior-1.3.0",
    ] = "speech-combat-behavior-1.1.0"
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
    utterance_cadence: SpeechCadence | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def selected_option(self) -> HumanChoiceEvidence:
        if self.version == SUPPORT_EVIDENCE_VERSION:
            if not self.frame.support_targets or (
                self.chosen_key.startswith("speech:") != (self.utterance_cadence is not None)
            ):
                raise ValueError(
                    "support evidence requires a support option and speech cadence when relevant"
                )
            aid_keys = {f"spell:MEND:{target}" for target in self.frame.support_targets}
            if {row.key for row in self.options if row.style == "HEAL_HELPER"} != aid_keys:
                raise ValueError("support choices must match the perceived helpers")
        elif self.frame.support_targets or any(row.style == "HEAL_HELPER" for row in self.options):
            raise ValueError("support options require the current evidence version")
        elif self.version == "speech-combat-behavior-1.2.0":
            if self.utterance_cadence is None or not self.chosen_key.startswith("speech:"):
                raise ValueError("cadence evidence requires a human speech choice")
        elif self.utterance_cadence is not None:
            raise ValueError("utterance cadence requires the current speech evidence version")
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
    action_sample_counts: dict[str, int] = Field(default_factory=dict, exclude_if=lambda v: not v)
    speech_cadence: SpeechCadence | None = Field(default=None, exclude_if=lambda v: v is None)
    cadence_evidence_event_ids: tuple[uuid.UUID, ...] = Field(
        default=(), exclude_if=lambda v: not v
    )

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
    # Compare priorities only when both contexts offered the same kind of healing.
    # Identities can differ while the observed relationship is the same.
    healing = {"HEAL_SELF", "HEAL_HELPER"}
    available_healing = {option.style for option in options if option.style in healing}
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
            and bool(row.frame.support_targets) == bool(frame.support_targets)
            and (
                not frame.support_targets
                or {option.style for option in row.options if option.style in healing}
                == available_healing
            )
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
    selected_counts = Counter(option.category for option in choices)
    offered_counts: Counter[tuple[str, str, str]] = Counter()
    for _, row in matching:
        offered_counts.update({option.category for option in row.options})
    cadence_samples = [
        (event, row.utterance_cadence)
        for event, row in matching
        if row.utterance_cadence is not None
    ]
    cadence_counts = Counter(cadence for _, cadence in cadence_samples)
    cadence_fields = {}
    if cadence_counts:
        cadence, count = cadence_counts.most_common(1)[0]
        if count >= 2 and count * 2 > len(cadence_samples):
            cadence_fields = {
                "speech_cadence": cadence,
                "cadence_evidence_event_ids": tuple(
                    event for event, sample in cadence_samples if sample == cadence
                ),
            }
    confidence = len(matching) / (len(matching) + 3)
    identity = context.identity.authored_identity if context.identity else None
    text = (
        " ".join((identity.backstory, *identity.motives, *identity.values)).lower()
        if identity
        else ""
    )
    peaceful = any(word in text for word in ("pacifist", "peaceful", "mercy", "avoid violence"))
    aggressive = any(word in text for word in ("aggressive", "vengeful", "warrior", "bold"))
    protective = any(
        word in text for word in ("protect others", "help others", "protect my friends")
    )
    levels = {"LOW": 0.25, "MEDIUM": 0.55, "HIGH": 0.85}
    risk = levels.get(str(persona.deep_traits.get("risk_tolerance")), 0.55)
    social = levels.get(str(persona.deep_traits.get("extraversion")), 0.55)
    direct = persona.deep_traits.get("communication_directness") == "DIRECT"
    avoid = persona.deep_traits.get("conflict_style") == "AVOID"
    battle = bool(frame and frame.threats)
    scores = {}
    sample_counts = {}
    for option in options:
        if option.kind == "GUARD":
            base = 0.8 + (1 if frame and frame.spatial.injured else 0) + (0.6 if avoid else 0)
        elif option.kind == "SPELL" and option.style == "HEAL_SELF":
            base = 3.5 if frame and frame.spatial.injured else 0.5
        elif option.kind == "SPELL" and option.style == "HEAL_HELPER":
            base = 2.0 if protective else 1.1
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
        count = offered_counts[option.category]
        chosen = selected_counts[option.category]
        passed = count - chosen
        sample_counts[option.key] = count
        scores[option.key] = round(
            (3 * base + 6 * chosen + min(0.0, base - 0.25) * passed) / (count + 3), 6
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
        active=bool(frame and (frame.threats or frame.speech_ready or frame.support_targets)),
        comparable_count=len(matching),
        confidence=confidence,
        evidence_event_ids=tuple(event for event, _ in matching),
        action_scores=scores,
        conflicts=conflicts,
        **({"action_sample_counts": sample_counts} if sample_counts else {}),
        **cadence_fields,
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
