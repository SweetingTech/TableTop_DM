"""Versioned tabletop mechanics. Action callers choose targets, not these values."""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.effects import timed_conditions

RULES_VERSION = "tabletop-action-rules-1.2.0"
WeaponId = Literal["UNARMED", "SHORTSWORD", "SPEAR"]
SpellId = Literal["ARCANE_BOLT", "MEND"]
DEFAULT_SPELLS: tuple[SpellId, ...] = ("ARCANE_BOLT", "MEND")


class WeaponRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    weapon_id: str
    damage_dice: int = Field(ge=1, le=20)
    damage_sides: int = Field(ge=2, le=100)
    reach: int = Field(ge=1, le=10)
    finesse: bool = False


WEAPONS = MappingProxyType(
    {
        "UNARMED": WeaponRule(weapon_id="UNARMED", damage_dice=1, damage_sides=6, reach=1),
        "SHORTSWORD": WeaponRule(
            weapon_id="SHORTSWORD", damage_dice=1, damage_sides=6, reach=1, finesse=True
        ),
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
    ability: Literal["strength", "dexterity"] | None = None
    proficiency_bonus: int = Field(default=0, ge=0, le=6)


class AbilityScores(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    strength: int = Field(default=10, ge=1, le=30)
    dexterity: int = Field(default=10, ge=1, le=30)
    constitution: int = Field(default=10, ge=1, le=30)
    intelligence: int = Field(default=10, ge=1, le=30)
    wisdom: int = Field(default=10, ge=1, le=30)
    charisma: int = Field(default=10, ge=1, le=30)


class BodyTraining(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proficiency_bonus: int = Field(default=2, ge=0, le=6)
    trained_weapons: tuple[WeaponId, ...] = Field(
        default=("UNARMED", "SHORTSWORD", "SPEAR"), max_length=3
    )


def conditions(body: dict) -> frozenset[str]:
    return frozenset(str(value).casefold() for value in body.get("conditions", ())) | frozenset(
        row.condition for row in timed_conditions(body).values()
    )


def capable(body: dict) -> bool:
    return int(body.get("hp", 0)) > 0 and not body.get("asleep") and not incapacitated(body)


def dead(body: dict) -> bool:
    return bool(
        body.get("dead")
        or str(body.get("status", "")).upper() == "DEAD"
        or "dead" in conditions(body)
    )


def incapacitated(body: dict) -> bool:
    """Voluntary-action boundary; legacy bodies without an HP field are not presumed dead.

    Sleep is handled separately: a human may wake by acting, but cannot wake out of
    unconsciousness, paralysis or death. Combat still requires explicit positive HP.
    """
    return bool(
        dead(body)
        or ("hp" in body and int(body["hp"]) <= 0)
        or body.get("defeated")
        or str(body.get("status", "")).upper() in {"DEFEATED", "UNCONSCIOUS", "INCAPACITATED"}
        or conditions(body).intersection({"incapacitated", "stunned", "unconscious", "paralyzed"})
    )


def attack_profile(body: dict) -> AttackProfile:
    weapon_id = str(body.get("equipped_weapon", "UNARMED")).upper()
    weapon = WEAPONS.get(weapon_id)
    if weapon is None:
        raise ValueError("equipped weapon is not a registered weapon")
    if weapon_id != "UNARMED" and int(body.get("inventory", {}).get(weapon_id, 0)) < 1:
        raise ValueError("equipped weapon is not owned by this body")
    ability: Literal["strength", "dexterity"] | None = None
    proficiency = 0
    attack_bonus, damage_bonus = body.get("attack_bonus", 0), body.get("damage_bonus", 0)
    if "ability_scores" in body:
        scores = AbilityScores.model_validate(body["ability_scores"])
        training = BodyTraining.model_validate(
            {name: body[name] for name in ("proficiency_bonus", "trained_weapons") if name in body}
        )
        ability = (
            "dexterity" if weapon.finesse and scores.dexterity > scores.strength else "strength"
        )
        modifier = (getattr(scores, ability) - 10) // 2
        proficiency = training.proficiency_bonus if weapon_id in training.trained_weapons else 0
        attack_bonus, damage_bonus = modifier + proficiency, modifier
    return AttackProfile(
        weapon=weapon,
        attack_bonus=attack_bonus,
        damage_bonus=damage_bonus,
        reach=body.get("reach", weapon.reach) if weapon_id == "UNARMED" else weapon.reach,
        disadvantage=bool(conditions(body).intersection({"poisoned", "frightened"})),
        ability=ability,
        proficiency_bonus=proficiency,
    )


def available_melee_reach(body: dict) -> int:
    """Own-loadout availability for scenes; invalid equipment cannot prevent a read."""
    try:
        return attack_profile(body).reach
    except ValueError:
        return 0


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
