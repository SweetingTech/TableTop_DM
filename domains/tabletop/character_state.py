"""Allowlisted read projection; authored cards never own a bound body's resources."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domains.tabletop.portal import CharacterRecord
from domains.tabletop.rules import conditions, dead, incapacitated, known_spells
from kernel.contracts import BranchKind
from kernel.state import BranchState


class CharacterBodyUnavailable(ValueError):
    """A bound card must not fall back to stale authored resource values."""


class LiveBodyState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    world_id: uuid.UUID
    branch_id: uuid.UUID
    entity_id: uuid.UUID
    projection_version: int = Field(ge=0)
    status: Literal["ALIVE", "ASLEEP", "INCAPACITATED", "DEFEATED", "DEAD"]
    hp: int = Field(ge=0)
    max_hp: int = Field(ge=0)
    armor: int
    speed: int = Field(ge=0)
    mana: int = Field(ge=0)
    inventory: dict[str, int]
    equipped_weapon: str
    known_spells: tuple[str, ...]
    conditions: tuple[str, ...]


class CharacterStateView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    character_id: uuid.UUID
    card_version: str
    source: Literal["AUTHORED", "KERNEL"]
    body: LiveBodyState | None = None

    @model_validator(mode="after")
    def consistent_source(self) -> CharacterStateView:
        if (self.source == "KERNEL") != (self.body is not None):
            raise ValueError("character state source and body disagree")
        return self


def project_character_state(
    character: CharacterRecord, state: BranchState | None
) -> CharacterStateView:
    """API composition authorizes owner, world and body before this pure read."""
    if character.entity_id is None:
        return CharacterStateView(
            character_id=character.character_id,
            card_version=character.card_version,
            source="AUTHORED",
        )
    if (
        state is None
        or state.world_id != character.world_id
        or state.kind is not BranchKind.CANONICAL
    ):
        raise CharacterBodyUnavailable("the bound canonical body is unavailable")
    body = state.projections.get("tabletop.entities", {}).get(str(character.entity_id))
    if body is None:
        raise CharacterBodyUnavailable("the bound canonical body is unavailable")
    hp = body.get("hp", 0)
    status = (
        "DEAD"
        if dead(body)
        else "DEFEATED"
        if body.get("defeated") or hp <= 0
        else "INCAPACITATED"
        if incapacitated(body)
        else "ASLEEP"
        if body.get("asleep")
        else "ALIVE"
    )
    return CharacterStateView(
        character_id=character.character_id,
        card_version=character.card_version,
        source="KERNEL",
        body=LiveBodyState(
            world_id=state.world_id,
            branch_id=state.branch_id,
            entity_id=character.entity_id,
            projection_version=state.version,
            status=status,
            hp=hp,
            max_hp=body.get("max_hp", hp),
            armor=body.get("armor", 10),
            speed=body.get("speed", 0),
            mana=body.get("mana", 0),
            inventory=dict(sorted(body.get("inventory", {}).items())),
            equipped_weapon=str(body.get("equipped_weapon", "UNARMED")),
            known_spells=known_spells(body),
            conditions=tuple(sorted(conditions(body))),
        ),
    )
