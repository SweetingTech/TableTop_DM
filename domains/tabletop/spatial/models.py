from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SpatialPosition(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    zone_id: uuid.UUID | str = "world"
    x: int
    y: int
    z: int = 0
    facing: str | None = None


class SpatialZone(BaseModel):
    model_config = ConfigDict(frozen=True)

    zone_id: uuid.UUID | str
    name: str
    ambient_light: float = Field(default=1.0, ge=0, le=1)
    ambient_noise: float = Field(default=0.0, ge=0, le=1)


class SpatialPortal(BaseModel):
    model_config = ConfigDict(frozen=True)

    portal_id: uuid.UUID
    from_zone_id: uuid.UUID | str
    to_zone_id: uuid.UUID | str
    kind: Literal["DOOR", "WINDOW", "OPENING", "PASSAGE"]
    state: Literal["OPEN", "CLOSED", "LOCKED"] = "OPEN"
    sight_transmission: float = Field(default=1.0, ge=0, le=1)
    sound_transmission: float = Field(default=1.0, ge=0, le=1)
    movement_allowed: bool = True


class SpatialOccluder(BaseModel):
    model_config = ConfigDict(frozen=True)

    zone_id: uuid.UUID | str = "world"
    x: int
    y: int
    blocks_movement: bool = True
    sight_opacity: float = Field(default=1.0, ge=0, le=1)
    sound_attenuation: float = Field(default=0.2, ge=0, le=1)
