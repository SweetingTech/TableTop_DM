"""Decision features derived only from validated character experience and perceived bodies."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from cognition.behavior import MovementFrame, movement_frame
from cognition.models import Observation
from domains.tabletop.spatial.scene import PerceivedScene

SPEECH = {
    "GREET": "Hello. Good to see you.",
    "ASK": "What do you need?",
    "DEESCALATE": "I do not want to fight. Can we talk?",
    "ASSERT": "Stay back. I am ready to defend myself.",
}
VOLUMES = ("WHISPER", "NORMAL", "LOUD", "SHOUT")


def speech_intent(text: str) -> str:
    lowered = text.lower()
    if any(
        word in lowered for word in ("peace", "calm", "talk", "don't fight", "do not want", "sorry")
    ):
        return "DEESCALATE"
    if "?" in text:
        return "ASK"
    if any(word in lowered for word in ("back", "fight", "attack", "defend", "stop")):
        return "ASSERT"
    return "GREET"


class KnownThreat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: uuid.UUID
    distance: int = Field(ge=0)
    wounded: bool


class ChoiceFrame(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    spatial: MovementFrame
    threats: tuple[KnownThreat, ...]
    speech_ready: bool

    @property
    def signature(self) -> tuple:
        spatial = self.spatial
        return (
            spatial.zone,
            spatial.injured,
            spatial.company,
            spatial.layout,
            min(2, len(self.threats)),
            self.speech_ready,
        )


def choice_frame(
    scene: PerceivedScene, observations: tuple[Observation, ...]
) -> ChoiceFrame | None:
    spatial = movement_frame(scene)
    body = next(
        (row for row in scene.perceived_entities if row.entity_id == scene.observer_entity_id), None
    )
    if spatial is None or body is None or body.position is None:
        return None
    attacks: dict[uuid.UUID, int] = {}
    own_speech = -1
    other_speech = own_speech
    # The trusted resolver supplies canonical source-event order, including clock ties.
    for index, observation in enumerate(observations):
        payload = observation.perceived_payload
        if str(payload.get("target_id")) == str(body.entity_id) and payload.get("attacker_id"):
            try:
                attacker = uuid.UUID(str(payload["attacker_id"]))
            except ValueError:
                continue
            attacks[attacker] = index
        if payload.get("speaker_entity_id") and isinstance(payload.get("text"), str):
            if str(payload["speaker_entity_id"]) == str(body.entity_id):
                own_speech = index
            else:
                other_speech = index
    threats = []
    for row in scene.perceived_entities:
        if (
            row.entity_id not in attacks
            or row.entity_id == body.entity_id
            or row.position is None
            or row.position.zone_id != body.position.zone_id
            or row.status in {"DEAD", "DEFEATED", "UNCONSCIOUS", "INCAPACITATED"}
            or (row.health is not None and row.health <= 0)
        ):
            continue
        distance = max(abs(row.position.x - body.position.x), abs(row.position.y - body.position.y))
        threats.append(
            KnownThreat(
                entity_id=row.entity_id,
                distance=distance,
                wounded=bool(
                    row.health is not None and row.max_health and row.health < row.max_health / 2
                ),
            )
        )
    threats.sort(key=lambda row: (row.distance, str(row.entity_id)))
    latest_attack = max((attacks[row.entity_id] for row in threats), default=own_speech)
    return ChoiceFrame(
        spatial=spatial,
        threats=tuple(threats[:8]),
        speech_ready=bool(spatial.company and max(other_speech, latest_attack) > own_speech),
    )
