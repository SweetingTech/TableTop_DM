from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CameraMode(StrEnum):
    TACTICAL = "TACTICAL"
    THIRD_PERSON = "THIRD_PERSON"
    FIRST_PERSON = "FIRST_PERSON"


class ControlAuthorityMode(StrEnum):
    FORMATION = "FORMATION"
    DIRECT = "DIRECT"


class SquadOrderKind(StrEnum):
    FOLLOW = "FOLLOW"
    HOLD = "HOLD"
    FOCUS = "FOCUS"
    SPREAD = "SPREAD"
    REGROUP = "REGROUP"


class FocusPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    z: float = 0


class SetControlModeRequest(BaseModel):
    camera_mode: CameraMode


class SetControlModeResult(BaseModel):
    entity_id: uuid.UUID
    previous_camera_mode: CameraMode
    camera_mode: CameraMode
    control_authority: ControlAuthorityMode
    squad_ai: str
    revision: int = Field(ge=1)


class SquadOrderRequest(BaseModel):
    squad_id: uuid.UUID
    order: SquadOrderKind
    target_entity_id: uuid.UUID | None = None
    focus_point: FocusPoint | None = None

    @model_validator(mode="after")
    def focus_requires_a_target(self) -> SquadOrderRequest:
        if (
            self.order is SquadOrderKind.FOCUS
            and self.target_entity_id is None
            and self.focus_point is None
        ):
            raise ValueError("FOCUS requires a target entity or focus point")
        return self


class SquadOrderResult(BaseModel):
    squad_id: uuid.UUID
    leader_entity_id: uuid.UUID
    order: SquadOrderKind
    target_entity_id: uuid.UUID | None = None
    focus_point: FocusPoint | None = None
    squad_ai: str
    revision: int = Field(ge=1)


class WeaponDefinition(BaseModel):
    """One weapon contract consumed by aggregate and direct-control systems."""

    model_config = ConfigDict(frozen=True)

    weapon_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    damage: float = Field(gt=0)
    fire_rate: float = Field(gt=0, description="Rounds per second")
    range: float = Field(gt=0)
    magazine: int = Field(gt=0)
    reload_time: float = Field(ge=0)
    recoil: float = Field(ge=0)
    spread: float = Field(ge=0)
    projectile_speed: float = Field(gt=0)
    penetration: float = Field(ge=0)
    squad_accuracy: float = Field(ge=0, le=1)
    asset_ref: str | None = Field(default=None, max_length=500)


class WeaponModifiers(BaseModel):
    model_config = ConfigDict(frozen=True)

    damage: float = Field(default=1, gt=0)
    fire_rate: float = Field(default=1, gt=0)
    range: float = Field(default=1, gt=0)
    magazine: float = Field(default=1, gt=0)
    reload_time: float = Field(default=1, gt=0)
    recoil: float = Field(default=1, gt=0)
    spread: float = Field(default=1, gt=0)
    projectile_speed: float = Field(default=1, gt=0)
    penetration: float = Field(default=1, gt=0)
    squad_accuracy: float = Field(default=1, gt=0)


class ResolvedWeaponStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    weapon_id: str
    name: str
    damage: float
    fire_rate: float
    range: float
    magazine: int
    reload_time: float
    recoil: float
    spread: float
    projectile_speed: float
    penetration: float
    squad_accuracy: float
    asset_ref: str | None = None

    @classmethod
    def resolve(
        cls, definition: WeaponDefinition, modifiers: WeaponModifiers | None = None
    ) -> ResolvedWeaponStats:
        modifiers = modifiers or WeaponModifiers()
        return cls(
            weapon_id=definition.weapon_id,
            name=definition.name,
            damage=round(definition.damage * modifiers.damage, 6),
            fire_rate=round(definition.fire_rate * modifiers.fire_rate, 6),
            range=round(definition.range * modifiers.range, 6),
            magazine=max(1, round(definition.magazine * modifiers.magazine)),
            reload_time=round(definition.reload_time * modifiers.reload_time, 6),
            recoil=round(definition.recoil * modifiers.recoil, 6),
            spread=round(definition.spread * modifiers.spread, 6),
            projectile_speed=round(definition.projectile_speed * modifiers.projectile_speed, 6),
            penetration=round(definition.penetration * modifiers.penetration, 6),
            squad_accuracy=round(min(1, definition.squad_accuracy * modifiers.squad_accuracy), 6),
            asset_ref=definition.asset_ref,
        )

    @property
    def squad_dps_contribution(self) -> float:
        return round(self.damage * self.fire_rate * self.squad_accuracy, 6)


class BattlefieldControlInput(BaseModel):
    """Renderer-agnostic input envelope for a future engine adapter."""

    model_config = ConfigDict(frozen=True)

    client_sequence: int = Field(ge=0)
    camera_mode: CameraMode
    action: str = Field(min_length=1, max_length=120)
    movement: FocusPoint | None = None
    target_entity_id: uuid.UUID | None = None
    parameters: dict[str, object] = Field(default_factory=dict)
