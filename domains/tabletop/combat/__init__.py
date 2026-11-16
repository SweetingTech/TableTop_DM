from __future__ import annotations

import random
import uuid

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.rules import RULES_VERSION, attack_profile, capable, dead
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.randomness import ActionRandomness
from kernel.state import BranchState


class AttackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: uuid.UUID


class AttackResult(BaseModel):
    rules_version: str = RULES_VERSION
    weapon_id: str = "UNARMED"
    attacker_id: uuid.UUID
    target_id: uuid.UUID
    attack_roll: int = Field(ge=1, le=20)
    hit: bool
    damage: int = Field(ge=0)
    hp_before: int = Field(ge=0)
    hp_after: int = Field(ge=0)
    randomness: ActionRandomness | None = None


def attack(proposal: CommandProposal, state: BranchState) -> CommandResult:
    attacker_id = proposal.embodied_entity_id
    if attacker_id is None or proposal.seed is None:
        raise ValueError("attacks require an embodied entity and explicit seed")
    request = AttackRequest.model_validate(proposal.parameters)
    entities = state.projections.get("tabletop.entities", {})
    attacker = entities.get(str(attacker_id))
    target = entities.get(str(request.target_id))
    if attacker is None or target is None:
        raise ValueError("attacker and target must exist")
    if attacker_id == request.target_id:
        raise ValueError("a melee attack requires another target")
    profile = attack_profile(attacker)
    positions = state.projections.get("tabletop.spatial.positions", {})
    origin, destination = (
        positions.get(str(attacker_id), attacker),
        positions.get(str(request.target_id), target),
    )
    distance = max(
        abs(int(origin.get("x", 0)) - int(destination.get("x", 0))),
        abs(int(origin.get("y", 0)) - int(destination.get("y", 0))),
    )
    if (
        distance > profile.reach
        or origin.get("zone_id", "world") != destination.get("zone_id", "world")
        or request.target_id
        not in GridSpatialPerceptionResolver().visible_entities(state, attacker_id)
    ):
        raise ValueError("target is not in visible melee reach")
    if not capable(attacker) or dead(target) or int(target.get("hp", -1)) < 0:
        raise ValueError("incapacitated entities cannot attack or be attacked")
    rng = random.Random(proposal.seed)
    attack_roll = rng.randint(1, 20)
    if profile.disadvantage:
        attack_roll = min(attack_roll, rng.randint(1, 20))
    hit = attack_roll == 20 or (
        attack_roll != 1
        and attack_roll + profile.attack_bonus
        >= int(target.get("armor", 10)) + (2 if target.get("guarded") else 0)
    )
    damage = 0
    if hit:
        damage = max(
            0,
            sum(
                rng.randint(1, profile.weapon.damage_sides)
                for _ in range(profile.weapon.damage_dice)
            )
            + profile.damage_bonus,
        )
    hp_before = int(target.get("hp", 0))
    hp_after = max(0, hp_before - damage)
    return CommandResult(
        result={
            "rules_version": RULES_VERSION,
            "weapon_id": profile.weapon.weapon_id,
            "attacker_id": str(attacker_id),
            "target_id": str(request.target_id),
            "attack_roll": attack_roll,
            "hit": hit,
            "damage": damage,
            "hp_before": hp_before,
            "hp_after": hp_after,
        },
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.target_id,
                values={
                    "hp": hp_after,
                    "defeated": hp_after == 0,
                    **({"guarded": False} if target.get("guarded") else {}),
                },
            ),
        ),
        domain_tags=("tabletop", "combat", "attack"),
    )


def attack_emission(
    proposal: CommandProposal, result: CommandResult, before: BranchState, after: BranchState
) -> EventEmission:
    del result, before, after
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="BEFORE"),
        modalities=(SensoryModality.SIGHT, SensoryModality.SOUND),
        max_range=8,
        allowed_payload_fields=("attacker_id", "target_id", "hit", "damage"),
        reason_codes=("combat.melee",),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.combat.attack",
        version="2.2.0",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=attack,
        request_model=AttackRequest,
        result_model=AttackResult,
        requires_controlled_entity=True,
        emission_builder=attack_emission,
        uses_randomness=True,
    )
