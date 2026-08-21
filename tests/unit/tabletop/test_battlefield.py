from __future__ import annotations

import copy
import uuid

import pytest

from domains.tabletop import register_tabletop
from domains.tabletop.battlefield import (
    BattlefieldFrameBuilder,
    CameraMode,
    ControlAuthorityMode,
    ResolvedWeaponStats,
    WeaponDefinition,
    WeaponModifiers,
)
from kernel.command_bus import CommandBus
from kernel.contracts import Actor, ActorKind, BranchKind, CommandProposal
from kernel.state import BranchState, InMemoryStateStore

pytestmark = pytest.mark.unit


@pytest.fixture
def battle():
    world_id, branch_id, run_id, actor_id = [uuid.uuid4() for _ in range(4)]
    leader_id, rifleman_a, rifleman_b, enemy_id, squad_id = [uuid.uuid4() for _ in range(5)]
    weapon = WeaponDefinition(
        weapon_id="service-rifle",
        name="Service Rifle",
        damage=10,
        fire_rate=8,
        range=120,
        magazine=30,
        reload_time=2.2,
        recoil=0.4,
        spread=0.2,
        projectile_speed=900,
        penetration=0.25,
        squad_accuracy=0.5,
        asset_ref="weapon://service-rifle",
    )
    state = BranchState(
        world_id,
        branch_id,
        BranchKind.TRIAL,
        {
            "tabletop.entities": {
                str(leader_id): {
                    "entity_type": "COMMANDER",
                    "name": "Mason",
                    "x": 0,
                    "y": 0,
                    "hp": 100,
                    "weapon_id": weapon.weapon_id,
                    "weapon_modifiers": {"fire_rate": 1.25},
                },
                str(rifleman_a): {
                    "entity_type": "RIFLEMAN",
                    "name": "Rifleman A",
                    "x": -1,
                    "y": 0,
                    "hp": 40,
                },
                str(rifleman_b): {
                    "entity_type": "RIFLEMAN",
                    "name": "Rifleman B",
                    "x": 1,
                    "y": 0,
                    "hp": 40,
                },
                str(enemy_id): {
                    "entity_type": "ELITE",
                    "name": "Unobserved Elite",
                    "x": 30,
                    "y": 10,
                    "hp": 250,
                },
            },
            "tabletop.squads": {
                str(squad_id): {
                    "leader_entity_id": str(leader_id),
                    "member_entity_ids": [str(rifleman_a), str(rifleman_b)],
                    "formation": "WEDGE",
                }
            },
            "tabletop.weapons": {weapon.weapon_id: weapon.model_dump(mode="json")},
        },
    )
    store = InMemoryStateStore()
    store.add(state)
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.HUMAN,
        display_name="Mason's player",
        capabilities=frozenset({"action.propose", "entity.act"}),
        controlled_entity_ids=frozenset({leader_id}),
    )
    return {
        "world": world_id,
        "branch": branch_id,
        "run": run_id,
        "actor": actor,
        "leader": leader_id,
        "rifleman_a": rifleman_a,
        "rifleman_b": rifleman_b,
        "enemy": enemy_id,
        "squad": squad_id,
        "state": state,
        "bus": register_tabletop(CommandBus(store)),
    }


def proposal(battle, command_type: str, parameters: dict, key: str) -> CommandProposal:
    return CommandProposal(
        command_type=command_type,
        world_id=battle["world"],
        branch_id=battle["branch"],
        run_id=battle["run"],
        actor_id=battle["actor"].actor_id,
        embodied_entity_id=battle["leader"],
        parameters=parameters,
        idempotency_key=key,
    )


def test_camera_modes_share_one_pawn_world_and_squad_ai(battle):
    entities_before = copy.deepcopy(battle["state"].projections["tabletop.entities"])
    squads_before = copy.deepcopy(battle["state"].projections["tabletop.squads"])
    weapons_before = copy.deepcopy(battle["state"].projections["tabletop.weapons"])

    third_person = battle["bus"].execute(
        proposal(
            battle,
            "tabletop.battlefield.set_control_mode",
            {"camera_mode": "THIRD_PERSON"},
            "third-person",
        ),
        battle["actor"],
    )
    order = battle["bus"].execute(
        proposal(
            battle,
            "tabletop.battlefield.issue_squad_order",
            {
                "squad_id": str(battle["squad"]),
                "order": "FOCUS",
                "target_entity_id": str(battle["enemy"]),
            },
            "focus-elite",
        ),
        battle["actor"],
    )
    first_person = battle["bus"].execute(
        proposal(
            battle,
            "tabletop.battlefield.set_control_mode",
            {"camera_mode": "FIRST_PERSON"},
            "first-person",
        ),
        battle["actor"],
    )
    tactical = battle["bus"].execute(
        proposal(
            battle,
            "tabletop.battlefield.set_control_mode",
            {"camera_mode": "TACTICAL"},
            "back-to-tactical",
        ),
        battle["actor"],
    )

    assert third_person.result.result["control_authority"] == "DIRECT"
    assert first_person.result.result["control_authority"] == "DIRECT"
    assert tactical.result.result["control_authority"] == "FORMATION"
    assert order.result.result["squad_ai"] == "ACTIVE"
    assert (
        battle["state"].projections["tabletop.squad_orders"][str(battle["squad"])]["order"]
        == "FOCUS"
    )
    assert battle["state"].projections["tabletop.entities"] == entities_before
    assert battle["state"].projections["tabletop.squads"] == squads_before
    assert battle["state"].projections["tabletop.weapons"] == weapons_before
    assert battle["state"].projections["tabletop.entities"][str(battle["leader"])]["hp"] == 100


def test_battlefield_frame_uses_authorized_visibility_and_shared_weapon_stats(battle):
    battle["bus"].execute(
        proposal(
            battle,
            "tabletop.battlefield.set_control_mode",
            {"camera_mode": "THIRD_PERSON"},
            "frame-third-person",
        ),
        battle["actor"],
    )
    frame = BattlefieldFrameBuilder.build(
        battle["state"],
        run_id=battle["run"],
        commander_entity_id=battle["leader"],
        visible_entity_ids=frozenset({battle["leader"], battle["rifleman_a"]}),
    )

    assert frame.camera_mode is CameraMode.THIRD_PERSON
    assert frame.control_authority is ControlAuthorityMode.DIRECT
    assert frame.commander.public_state["hp"] == 100
    assert {item.entity_id for item in frame.visible_entities} == {battle["rifleman_a"]}
    assert battle["enemy"] not in {item.entity_id for item in frame.visible_entities}
    assert frame.squad is not None
    assert frame.squad.member_entity_ids == (battle["rifleman_a"], battle["rifleman_b"])
    assert frame.weapon is not None
    assert frame.weapon.fire_rate == 10
    assert frame.weapon.squad_dps_contribution == 50


def test_weapon_upgrade_is_resolved_once_for_both_consumers():
    definition = WeaponDefinition(
        weapon_id="rifle",
        name="Rifle",
        damage=12,
        fire_rate=4,
        range=100,
        magazine=20,
        reload_time=2,
        recoil=0.5,
        spread=0.25,
        projectile_speed=800,
        penetration=0.1,
        squad_accuracy=0.5,
    )
    resolved = ResolvedWeaponStats.resolve(
        definition, WeaponModifiers(fire_rate=1.25, projectile_speed=1.1)
    )

    assert resolved.fire_rate == 5
    assert resolved.projectile_speed == 880
    assert resolved.squad_dps_contribution == 30


def test_focus_order_requires_a_target(battle):
    with pytest.raises(ValueError, match="Invalid tabletop.battlefield.issue_squad_order"):
        battle["bus"].execute(
            proposal(
                battle,
                "tabletop.battlefield.issue_squad_order",
                {"squad_id": str(battle["squad"]), "order": "FOCUS"},
                "invalid-focus",
            ),
            battle["actor"],
        )
