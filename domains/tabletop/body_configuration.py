"""Authorized body definitions and intent-only changes to an owned loadout."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.rules import (
    DEFAULT_SPELLS,
    RULES_VERSION,
    WEAPONS,
    AbilityScores,
    BodyTraining,
    SpellId,
    WeaponId,
)
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState


class ConfigureBodyRequest(BodyTraining):
    entity_id: uuid.UUID
    ability_scores: AbilityScores
    known_spells: tuple[SpellId, ...] = Field(default=DEFAULT_SPELLS, max_length=2)
    equipped_weapon: WeaponId = "UNARMED"


class ConfigureBodyResult(BaseModel):
    entity_id: uuid.UUID
    rules_version: str = RULES_VERSION


class EquipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weapon_id: WeaponId


class EquipResult(BaseModel):
    entity_id: uuid.UUID
    weapon_id: WeaponId
    rules_version: str = RULES_VERSION
    summary: str


def require_owned(body: dict, weapon_id: str) -> None:
    if weapon_id not in WEAPONS:
        raise ValueError("weapon is not registered")
    if weapon_id != "UNARMED" and int(body.get("inventory", {}).get(weapon_id, 0)) < 1:
        raise ValueError("weapon is not owned by this body")


def configure(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ConfigureBodyRequest.model_validate(proposal.parameters)
    body = state.projections.get("tabletop.entities", {}).get(str(request.entity_id))
    if body is None:
        raise ValueError("configuration requires an existing body")
    require_owned(body, request.equipped_weapon)
    values = request.model_dump(mode="json", exclude={"entity_id"})
    values["trained_weapons"] = sorted(set(values["trained_weapons"]))
    values["known_spells"] = sorted(set(values["known_spells"]))
    return CommandResult(
        result=ConfigureBodyResult(entity_id=request.entity_id).model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.entity_id,
                values=values,
            ),
        ),
        domain_tags=("operator", "body_configuration"),
    )


def equip(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = EquipRequest.model_validate(proposal.parameters)
    entity_id = proposal.embodied_entity_id
    body = state.projections.get("tabletop.entities", {}).get(str(entity_id))
    if entity_id is None or body is None:
        raise ValueError("equip requires an embodied body")
    require_owned(body, request.weapon_id)
    if body.get("equipped_weapon", "UNARMED") == request.weapon_id:
        raise ValueError("weapon is already equipped")
    return CommandResult(
        result=EquipResult(
            entity_id=entity_id,
            weapon_id=request.weapon_id,
            summary="An unarmed fighting stance was taken."
            if request.weapon_id == "UNARMED"
            else f"A {request.weapon_id.lower()} was readied.",
        ).model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=entity_id,
                values={"equipped_weapon": request.weapon_id},
            ),
        ),
        domain_tags=("tabletop", "equipment"),
    )


def equip_emission(proposal, result, before, after) -> EventEmission:
    del result, before, after
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="AFTER"),
        modalities=(SensoryModality.SIGHT,),
        max_range=2,
        allowed_payload_fields=("entity_id", "weapon_id", "summary"),
        reason_codes=("equipment.change",),
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    branches = frozenset({BranchKind.CANONICAL, BranchKind.TRIAL})
    return (
        CommandDefinition(
            command_type="tabletop.body.configure",
            version=RULES_VERSION,
            required_capabilities=frozenset({"action.propose", "entity.control"}),
            allowed_branch_kinds=branches,
            handler=configure,
            request_model=ConfigureBodyRequest,
            result_model=ConfigureBodyResult,
        ),
        CommandDefinition(
            command_type="tabletop.equipment.equip",
            version=RULES_VERSION,
            required_capabilities=frozenset({"action.propose", "entity.act"}),
            allowed_branch_kinds=branches,
            requires_controlled_entity=True,
            handler=equip,
            request_model=EquipRequest,
            result_model=EquipResult,
            emission_builder=equip_emission,
        ),
    )
