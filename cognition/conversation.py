"""Private reply schedules derived from committed character experience."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from cognition.context import CharacterContext
from kernel.contracts import EventEnvelopeV2
from kernel.control import ControllerState
from kernel.perception_contracts import NON_SENSORY_TAGS


class ReplySchedule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["reply-schedule-1.0.0"] = "reply-schedule-1.0.0"
    source_event_id: uuid.UUID
    source_observation_id: uuid.UUID
    speaker_entity_id: uuid.UUID
    correlation_id: uuid.UUID
    source_language: str = Field(min_length=1, max_length=80)
    due_at: AwareDatetime


def due_reply(
    context: CharacterContext,
    controller: ControllerState,
    event_reader: Callable[[uuid.UUID], EventEnvelopeV2 | None],
    *,
    now: datetime,
) -> ReplySchedule | None:
    """Recover the latest unconsumed reply from the body's ordered observations."""
    if (
        controller.mode != "AUTONOMOUS"
        or controller.next_due > now
        or (context.scene.world_id, context.scene.branch_id, context.scene.observer_entity_id)
        != (controller.world_id, controller.branch_id, controller.entity_id)
    ):
        return None
    for observation in reversed(context.observations):
        payload = observation.perceived_payload
        speaker = payload.get("speaker_entity_id")
        text = payload.get("text")
        if (
            observation.observer_entity_id != controller.entity_id
            or not speaker
            or not isinstance(text, str)
            or not text.strip()
        ):
            continue
        event = event_reader(observation.source_event_id)
        if (
            event is None
            or event.event_type != "tabletop.dialogue.speak"
            or NON_SENSORY_TAGS.intersection(event.domain_tags)
            or (event.world_id, event.branch_id, event.run_id) != controller.key[:3]
            or event.embodied_entity_id is None
            or str(event.embodied_entity_id) != str(speaker)
        ):
            continue
        scheduled = max(event.created_at, observation.observed_at, controller.next_due)
        if event.embodied_entity_id == controller.entity_id or scheduled > now:
            return None
        return ReplySchedule(
            source_event_id=event.event_id,
            source_observation_id=observation.observation_id,
            speaker_entity_id=event.embodied_entity_id,
            correlation_id=event.correlation_id,
            source_language=str(payload.get("language") or "common"),
            due_at=scheduled,
        )
    return None
