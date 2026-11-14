from __future__ import annotations

import random
import uuid

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState


class AttackRequest(BaseModel):
    target_id: uuid.UUID
    attack_bonus: int = Field(default=0, ge=-10, le=30)
    damage_dice: int = Field(default=1, ge=1, le=20)
    damage_sides: int = Field(default=6, ge=2, le=100)
    damage_bonus: int = Field(default=0, ge=-10, le=100)


class AttackResult(BaseModel):
    attacker_id: uuid.UUID
    target_id: uuid.UUID
    attack_roll: int = Field(ge=1, le=20)
    hit: bool
    damage: int = Field(ge=0)
    hp_before: int = Field(ge=0)
    hp_after: int = Field(ge=0)


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
    distance = max(
        abs(int(attacker.get("x", 0)) - int(target.get("x", 0))),
        abs(int(attacker.get("y", 0)) - int(target.get("y", 0))),
    )
    if distance > int(attacker.get("reach", 1)):
        raise ValueError("target is out of reach")
    if int(attacker.get("hp", 0)) <= 0 or int(target.get("hp", 0)) <= 0:
        raise ValueError("incapacitated entities cannot attack or be attacked")
    rng = random.Random(proposal.seed)
    attack_roll = rng.randint(1, 20)
    hit = attack_roll == 20 or (
        attack_roll != 1
        and attack_roll + request.attack_bonus
        >= int(target.get("armor", 10)) + (2 if target.get("guarded") else 0)
    )
    damage = 0
    if hit:
        damage = max(
            0,
            sum(rng.randint(1, request.damage_sides) for _ in range(request.damage_dice))
            + request.damage_bonus,
        )
    hp_before = int(target.get("hp", 0))
    hp_after = max(0, hp_before - damage)
    return CommandResult(
        result={
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
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=attack,
        request_model=AttackRequest,
        result_model=AttackResult,
        requires_controlled_entity=True,
        emission_builder=attack_emission,
    )
