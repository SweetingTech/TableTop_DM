from __future__ import annotations

import uuid

import pytest

from cognition.engine import SubjectiveStatePipeline
from cognition.perception import PerceptionProfile
from domains.tabletop import register_tabletop
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from identity.repository import kernel_authority
from kernel.command_bus import CommandBus
from kernel.contracts import Actor, ActorKind, BranchKind, CommandProposal
from kernel.errors import AuthorizationDenied
from kernel.state import BranchState, InMemoryStateStore

pytestmark = pytest.mark.unit


def _world():
    world_id, branch_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    speaker, listener, back_room = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    source_actor, listener_actor, system_actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    portal_id = uuid.uuid4()
    state = BranchState(
        world_id=world_id,
        branch_id=branch_id,
        kind=BranchKind.CANONICAL,
        projections={
            "tabletop.entities": {
                str(speaker): {"name": "NPC 1", "x": 1, "y": 1, "zone_id": "common"},
                str(listener): {"name": "Player 1", "x": 2, "y": 1, "zone_id": "common"},
                str(back_room): {"name": "Player 2", "x": 1, "y": 1, "zone_id": "back"},
            },
            "tabletop.spatial.zones": {
                "common": {"name": "Tavern common room"},
                "back": {"name": "Back room"},
            },
            "tabletop.spatial.portals": {
                str(portal_id): {
                    "from_zone_id": "common",
                    "to_zone_id": "back",
                    "kind": "DOOR",
                    "state": "CLOSED",
                    "sight_transmission": 0,
                    "sound_transmission": 1,
                    "movement_allowed": False,
                }
            },
            "tabletop.sensory_profiles": {
                str(speaker): {"controller_actor_id": str(source_actor)},
                str(listener): {"controller_actor_id": str(listener_actor)},
                str(back_room): {"controller_actor_id": str(system_actor)},
            },
        },
    )
    store = InMemoryStateStore()
    store.add(state)
    bus = register_tabletop(CommandBus(store))
    actor = Actor(
        actor_id=source_actor,
        kind=ActorKind.AGENT,
        display_name="NPC controller",
        capabilities=frozenset({"action.propose", "action.commit", "entity.act"}),
        controlled_entity_ids=frozenset({speaker}),
    )
    return {
        "world": world_id,
        "branch": branch_id,
        "run": run_id,
        "speaker": speaker,
        "listener": listener,
        "back_room": back_room,
        "source_actor": source_actor,
        "listener_actor": listener_actor,
        "system_actor": system_actor,
        "portal": portal_id,
        "state": state,
        "bus": bus,
        "actor": actor,
    }


def _speak(fixture, key: str, volume: str = "NORMAL"):
    return fixture["bus"].execute(
        CommandProposal(
            command_type="tabletop.dialogue.speak",
            world_id=fixture["world"],
            branch_id=fixture["branch"],
            run_id=fixture["run"],
            actor_id=fixture["source_actor"],
            embodied_entity_id=fixture["speaker"],
            parameters={
                "text": "The king is dead.",
                "volume": volume,
                "language": "common",
                "claims": [
                    {
                        "subject_type": "person",
                        "predicate": "king_status",
                        "value": "DEAD",
                    }
                ],
            },
            idempotency_key=key,
        ),
        fixture["actor"],
    )


def test_closed_room_freezes_entity_level_witnesses_and_keeps_raw_acl_narrow():
    fixture = _world()
    receipt = _speak(fixture, "closed-normal")

    grants = {grant.observer_entity_id: grant for grant in receipt.perceptions}
    assert set(grants) == {fixture["speaker"], fixture["listener"]}
    assert fixture["back_room"] not in grants
    assert receipt.event.visible_to == (fixture["source_actor"],)
    assert set(receipt.event.observed_by) == {
        fixture["source_actor"],
        fixture["listener_actor"],
    }

    # Entering the room later cannot alter the frozen event-time audience.
    fixture["state"].projections["tabletop.entities"][str(fixture["back_room"])]["zone_id"] = (
        "common"
    )
    assert fixture["back_room"] not in {item.observer_entity_id for item in receipt.perceptions}


def test_open_door_or_shout_changes_hearing_deterministically():
    opened = _world()
    opened["state"].projections["tabletop.spatial.portals"][str(opened["portal"])]["state"] = "OPEN"
    first = _speak(opened, "open-normal")
    assert opened["back_room"] in {grant.observer_entity_id for grant in first.perceptions}

    closed = _world()
    shout = _speak(closed, "closed-shout", "SHOUT")
    assert closed["back_room"] in {grant.observer_entity_id for grant in shout.perceptions}

    repeated_shout = _speak(closed, "closed-shout", "SHOUT")
    assert repeated_shout.perceptions == shout.perceptions


def test_one_controller_with_multiple_bodies_does_not_share_physical_knowledge():
    fixture = _world()
    second_system_body = uuid.uuid4()
    fixture["state"].projections["tabletop.entities"][str(second_system_body)] = {
        "name": "Goblin B",
        "x": 8,
        "y": 8,
        "zone_id": "back",
    }
    fixture["state"].projections["tabletop.sensory_profiles"][str(second_system_body)] = {
        "controller_actor_id": str(fixture["system_actor"])
    }
    receipt = _speak(fixture, "multi-body")
    observed_entities = {grant.observer_entity_id for grant in receipt.perceptions}
    assert fixture["back_room"] not in observed_entities
    assert second_system_body not in observed_entities


def test_testimony_evidence_names_the_speaker_without_claiming_direct_witness():
    fixture = _world()
    receipt = _speak(fixture, "testimony")
    grant = next(
        item for item in receipt.perceptions if item.observer_entity_id == fixture["listener"]
    )
    update = SubjectiveStatePipeline().process(
        receipt.event,
        PerceptionProfile(
            observer_entity_id=fixture["listener"],
            observer_actor_id=fixture["listener_actor"],
        ),
        grant=grant,
    )
    assert update.evidence
    assert update.evidence[0].evidence_type == "TESTIMONY"
    assert update.evidence[0].immediate_source_entity_id == fixture["speaker"]
    assert update.evidence[0].direct_witness is False
    assert update.evidence[0].claimed_origin_event_id is None


def test_current_scene_sight_does_not_reveal_entities_behind_a_zone_boundary():
    fixture = _world()
    visible = GridSpatialPerceptionResolver().visible_entities(
        fixture["state"], fixture["listener"]
    )
    assert fixture["speaker"] in visible
    assert fixture["back_room"] not in visible


def test_player_role_can_act_only_through_an_explicitly_assigned_body():
    roles, capabilities = kernel_authority(is_admin=False, world_roles=frozenset({"PLAYER"}))
    assert roles == frozenset({"PLAYER"})
    assert "entity.act" in capabilities
    assert "entity.control" not in capabilities

    fixture = _world()
    other = fixture["actor"].model_copy(
        update={"controlled_entity_ids": frozenset({fixture["listener"]})}
    )
    with pytest.raises(AuthorizationDenied, match="does not control"):
        fixture["bus"].execute(
            CommandProposal(
                command_type="tabletop.spatial.move",
                world_id=fixture["world"],
                branch_id=fixture["branch"],
                run_id=fixture["run"],
                actor_id=fixture["source_actor"],
                embodied_entity_id=fixture["speaker"],
                parameters={"dx": 1, "dy": 0},
                idempotency_key="foreign-body",
            ),
            other,
        )
