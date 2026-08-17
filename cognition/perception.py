from __future__ import annotations

import copy
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cognition.models import Observation
from kernel.contracts import EventEnvelopeV2
from kernel.state import stable_hash


class PerceptionProfile(BaseModel):
    """Actor-specific controls for turning an authorized event into an observation."""

    model_config = ConfigDict(frozen=True)

    observer_entity_id: uuid.UUID
    observer_actor_id: uuid.UUID
    acuity: float = Field(default=1.0, ge=0, le=1)
    confidence_bias: float = Field(default=0.0, ge=-1, le=1)
    allowed_payload_fields: tuple[str, ...] | None = None
    hidden_payload_fields: frozenset[str] = frozenset()
    payload_overrides: dict[str, Any] = Field(default_factory=dict)


class PerceptionEngine:
    """Deterministic visibility and perception filter; canonical payloads stay untouched."""

    VERSION = "perception-1.0.0"

    def observe(
        self,
        event: EventEnvelopeV2,
        profile: PerceptionProfile,
        *,
        base_confidence: float = 1.0,
    ) -> Observation | None:
        if profile.observer_actor_id not in event.visible_to:
            return None
        if event.observed_by and profile.observer_actor_id not in event.observed_by:
            return None

        payload = copy.deepcopy(event.payload)
        if profile.allowed_payload_fields is not None:
            allowed = set(profile.allowed_payload_fields)
            payload = {key: value for key, value in payload.items() if key in allowed}
        for field in profile.hidden_payload_fields:
            payload.pop(field, None)
        payload.update(copy.deepcopy(profile.payload_overrides))

        confidence = max(
            0.0,
            min(1.0, base_confidence * profile.acuity + profile.confidence_bias),
        )
        observation_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    "tabletop-dm:observation",
                    self.VERSION,
                    str(event.event_id),
                    str(profile.observer_entity_id),
                    stable_hash(payload),
                    f"{confidence:.6f}",
                )
            ),
        )
        return Observation(
            observation_id=observation_id,
            observer_entity_id=profile.observer_entity_id,
            source_event_id=event.event_id,
            perceived_payload=payload,
            confidence=round(confidence, 6),
            observed_at=event.created_at,
        )
