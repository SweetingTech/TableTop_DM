"""Versioned tabletop mechanics. Action callers choose targets, not these values."""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RULES_VERSION = "tabletop-action-rules-1.0.0"
SpellId = Literal["ARCANE_BOLT", "MEND"]
DEFAULT_SPELLS: tuple[SpellId, ...] = ("ARCANE_BOLT", "MEND")


class WeaponRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    weapon_id: str
    damage_dice: int = Field(ge=1, le=20)
    damage_sides: int = Field(ge=2, le=100)
    reach: int = Field(ge=1, le=10)


WEAPONS = MappingProxyType(
    {
        "UNARMED": WeaponRule(weapon_id="UNARMED", damage_dice=1, damage_sides=6, reach=1),
        "SHORTSWORD": WeaponRule(weapon_id="SHORTSWORD", damage_dice=1, damage_sides=6, reach=1),
        "SPEAR": WeaponRule(weapon_id="SPEAR", damage_dice=1, damage_sides=8, reach=2),
    }
)


class AttackProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    weapon: WeaponRule
    attack_bonus: int = Field(default=0, ge=-10, le=30)
    damage_bonus: int = Field(default=0, ge=-10, le=100)
    reach: int = Field(ge=1, le=10)
    disadvantage: bool = False


def conditions(body: dict) -> frozenset[str]:
    return frozenset(str(value).casefold() for value in body.get("conditions", ()))


def capable(body: dict) -> bool:
    return (
        int(body.get("hp", 0)) > 0
        and not body.get("defeated")
        and not body.get("asleep")
        and not conditions(body).intersection(
            {"incapacitated", "stunned", "unconscious", "paralyzed", "dead"}
        )
    )


def attack_profile(body: dict) -> AttackProfile:
    weapon_id = str(body.get("equipped_weapon", "UNARMED")).upper()
    weapon = WEAPONS.get(weapon_id)
    if weapon is None:
        raise ValueError("equipped weapon is not a registered weapon")
    if weapon_id != "UNARMED" and int(body.get("inventory", {}).get(weapon_id, 0)) < 1:
        raise ValueError("equipped weapon is not owned by this body")
    return AttackProfile(
        weapon=weapon,
        attack_bonus=body.get("attack_bonus", 0),
        damage_bonus=body.get("damage_bonus", 0),
        reach=body.get("reach", weapon.reach) if weapon_id == "UNARMED" else weapon.reach,
        disadvantage=bool(conditions(body).intersection({"poisoned", "frightened"})),
    )


class SpellRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    spell_id: SpellId
    effect: Literal["DAMAGE", "HEAL"]
    power: int = Field(ge=1, le=10000)
    mana_cost: int = Field(ge=1, le=1000)
    reach: int = Field(ge=1, le=100)


SPELLS = MappingProxyType(
    {
        "ARCANE_BOLT": SpellRule(
            spell_id="ARCANE_BOLT", effect="DAMAGE", power=3, mana_cost=2, reach=6
        ),
        "MEND": SpellRule(spell_id="MEND", effect="HEAL", power=4, mana_cost=2, reach=2),
    }
)


def known_spells(body: dict) -> tuple[str, ...]:
    raw = body.get("known_spells", DEFAULT_SPELLS)
    if not isinstance(raw, (tuple, list)) or any(
        not isinstance(value, str) or value not in SPELLS for value in raw
    ):
        raise ValueError("body spell knowledge must contain registered spell IDs")
    return tuple(sorted(set(raw)))
