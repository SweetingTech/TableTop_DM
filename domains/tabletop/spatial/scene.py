from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SceneCoordinate(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int
    y: int
    z: int = 0
    zone_id: uuid.UUID | str = "world"


class PerceivedEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    name: str | None = None
    apparent_type: str | None = None
    position: SceneCoordinate | None = None
    position_confidence: float = Field(ge=0, le=1)
    knowledge_state: Literal["VISIBLE", "LAST_KNOWN", "RUMORED"]
    detail_level: Literal["PRESENCE", "CLASSIFIED", "IDENTIFIED", "INSPECTED"]
    observed_at: datetime | None = None
    health: int | None = None
    max_health: int | None = None
    status: str | None = None


class ObservationPresentation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: uuid.UUID
    source_event_id: uuid.UUID
    event_type: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime
    immediate_source_entity_id: uuid.UUID | None = None


class PerceivedScene(BaseModel):
    model_config = ConfigDict(frozen=True)

    observer_entity_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    projection_version: int
    visible_zones: tuple[str, ...]
    perceived_entities: tuple[PerceivedEntity, ...]
    recent_observations: tuple[ObservationPresentation, ...]
    available_viewpoints: tuple[uuid.UUID, ...]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
