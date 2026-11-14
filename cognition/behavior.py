"""Small, inspectable movement preferences; operational provenance is never character fiction."""

from __future__ import annotations

import re
import uuid
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cognition.context import CharacterContext
from cognition.engine import DecisionAction
from domains.tabletop.spatial.scene import PerceivedScene
from kernel.state import stable_hash
from persona.models import CompiledPersona

BEHAVIOR_VERSION: Final[Literal["movement-behavior-1.0.0"]] = "movement-behavior-1.0.0"
DIRECTIONS = {(0, -1): "north", (1, 0): "east", (0, 1): "south", (-1, 0): "west"}


def direction_for(parameters: dict[str, Any]) -> str:
    dx, dy = parameters.get("dx"), parameters.get("dy")
    return DIRECTIONS.get((dx, dy), "") if isinstance(dx, int) and isinstance(dy, int) else ""


class MovementOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    direction: Literal["north", "east", "south", "west"]
    approach: float = Field(ge=-1, le=1, allow_inf_nan=False)


class MovementFrame(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    zone: str
    injured: bool
    company: int = Field(ge=0, le=2)
    layout: tuple[tuple[int, int, int], ...]
    options: tuple[MovementOption, ...]

    @model_validator(mode="after")
    def complete_options(self) -> MovementFrame:
        if {row.direction for row in self.options} != set(DIRECTIONS.values()) or len(
            self.options
        ) != 4:
            raise ValueError("movement evidence requires four distinct options")
        return self


def movement_frame(scene: PerceivedScene) -> MovementFrame | None:
    body = next(
        (row for row in scene.perceived_entities if row.entity_id == scene.observer_entity_id), None
    )
    if body is None or body.position is None:
        return None
    here = body.position
    others = [
        row.position
        for row in scene.perceived_entities
        if row.entity_id != body.entity_id
        and row.position is not None
        and row.position.zone_id == here.zone_id
    ]
    options = []
    for (dx, dy), name in DIRECTIONS.items():
        changes = [
            abs(p.x - here.x) + abs(p.y - here.y) - abs(p.x - here.x - dx) - abs(p.y - here.y - dy)
            for p in others
        ]
        options.append(
            MovementOption(direction=name, approach=sum(changes) / len(changes) if changes else 0)
        )
    return MovementFrame(
        zone=str(here.zone_id),
        injured=bool(
            body.health is not None and body.max_health and body.health < body.max_health / 2
        ),
        company=min(2, len(others)),
        layout=tuple(
            sorted(
                {
                    (
                        (p.x > here.x) - (p.x < here.x),
                        (p.y > here.y) - (p.y < here.y),
                        min(2, (abs(p.x - here.x) + abs(p.y - here.y)) // 3),
                    )
                    for p in others
                }
            )
        ),
        options=tuple(options),
    )


class HumanMovementEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    player_actor_id: uuid.UUID
    character_id: uuid.UUID
    binding_id: uuid.UUID
    projection_version: int = Field(ge=0)
    frame: MovementFrame
    chosen: Literal["north", "east", "south", "west"]
    version: Literal["movement-behavior-1.0.0"] = BEHAVIOR_VERSION


class BehaviorProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str = BEHAVIOR_VERSION
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    character_id: uuid.UUID
    player_actor_id: uuid.UUID
    binding_id: uuid.UUID
    context_hash: str
    persona_version: str
    evidence_event_ids: tuple[uuid.UUID, ...]
    comparable_count: int = Field(ge=0, le=256)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    persona_approach: float
    authored_approach: float
    direction_scores: dict[str, float]
    conflicts: tuple[str, ...]

    @model_validator(mode="after")
    def verify_content_address(self) -> BehaviorProfile:
        if self.profile_id != stable_hash(self.model_dump(mode="json", exclude={"profile_id"})):
            raise ValueError("behavior profile content differs from its version")
        return self


def behavior_profile(
    context: CharacterContext,
    persona: CompiledPersona,
    *,
    character_id: uuid.UUID,
    binding_id: uuid.UUID,
    run_id: uuid.UUID,
    player_actor_id: uuid.UUID,
    evidence: tuple[tuple[uuid.UUID, HumanMovementEvidence], ...],
) -> BehaviorProfile:
    frame = movement_frame(context.scene)
    matching = sorted(
        (
            (event, row)
            for event, row in evidence
            if frame is not None
            and (
                row.world_id,
                row.branch_id,
                row.run_id,
                row.entity_id,
                row.character_id,
                row.player_actor_id,
            )
            == (
                context.scene.world_id,
                context.scene.branch_id,
                run_id,
                context.scene.observer_entity_id,
                character_id,
                player_actor_id,
            )
            and row.version == BEHAVIOR_VERSION
            and (row.frame.zone, row.frame.injured, row.frame.company, row.frame.layout)
            == (frame.zone, frame.injured, frame.company, frame.layout)
        ),
        key=lambda pair: str(pair[0]),
    )
    confidence = len(matching) / (len(matching) + 3)
    persona_approach = (persona.policy_weights.get("curiosity", 0.55) - 0.55) * 2
    persona_approach -= (persona.policy_weights.get("risk_penalty", 1.25) - 1.25) * (
        3 if frame and frame.injured else 1
    )
    # This bounded English vocabulary is intentionally explicit, not a semantic model.
    # Starting lore and secrets do not become instructions or preference evidence.
    identity = context.identity.authored_identity if context.identity else None
    text = " ".join((identity.backstory, *identity.motives, *identity.values)) if identity else ""
    words = set(re.findall(r"[a-z]+", text.lower()))
    cautious = bool(words & {"cautious", "caution", "careful", "avoid", "survive", "survival"})
    curious = bool(
        words
        & {"curious", "curiosity", "explore", "exploration", "discover", "discovery", "sociable"}
    )
    authored = 1.0 * curious - 1.0 * cautious
    scores = {
        option.direction: round(
            option.approach * (persona_approach + authored) * (1 - confidence)
            + 5
            * confidence
            * sum(row.chosen == option.direction for _, row in matching)
            / max(1, len(matching)),
            6,
        )
        for option in (frame.options if frame else ())
    }
    learned_approach = sum(
        next(option.approach for option in row.frame.options if option.direction == row.chosen)
        for _, row in matching
    ) / max(1, len(matching))
    conflicts: tuple[str, ...] = ()
    if len(matching) >= 3 and authored * learned_approach < -0.2:
        conflicts = (
            "Repeated human movement conflicts with the authored approach/avoid tendency; "
            "review the card or history.",
        )
    payload = dict(
        version=BEHAVIOR_VERSION,
        world_id=context.scene.world_id,
        branch_id=context.scene.branch_id,
        run_id=run_id,
        entity_id=context.scene.observer_entity_id,
        character_id=character_id,
        player_actor_id=player_actor_id,
        binding_id=binding_id,
        context_hash=context.evidence_hash,
        persona_version=persona.persona_version,
        evidence_event_ids=tuple(event for event, _ in matching),
        comparable_count=len(matching),
        confidence=confidence,
        persona_approach=round(persona_approach, 6),
        authored_approach=authored,
        direction_scores=scores,
        conflicts=conflicts,
    )
    return BehaviorProfile(profile_id=stable_hash(payload), **payload)


def weighted_actions(
    actions: tuple[DecisionAction, ...], profile: BehaviorProfile
) -> tuple[DecisionAction, ...]:
    return tuple(
        action.model_copy(
            update={
                "utility_factors": {
                    "behavior": profile.direction_scores.get(
                        direction_for(action.parameters),
                        0,
                    )
                }
            }
        )
        for action in actions
    )
