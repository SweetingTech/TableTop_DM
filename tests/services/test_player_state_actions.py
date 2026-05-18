import uuid

from services.player_state.actions import legal_actions_for
from services.player_state.visibility import is_spatially_visible


def test_legal_actions_disable_attack_when_no_visible_target():
    actions = legal_actions_for(
        mode="COMBAT",
        session_status="ACTIVE",
        controlled_entities=[{"id": "pc-a"}],
        visible_entities=[{"id": "pc-a", "entity_type": "PC"}],
        encounter={"id": "enc-1"},
        active_slot={"entity_id": "pc-a"},
    )

    attack = next(a for a in actions if a.action == "attack")
    assert attack.enabled is False
    assert attack.reason == "No visible hostile target in range."


def test_legal_actions_mark_my_turn_for_active_controlled_entity():
    actions = legal_actions_for(
        mode="COMBAT",
        session_status="ACTIVE",
        controlled_entities=[{"id": "pc-a"}],
        visible_entities=[{"id": "pc-a", "entity_type": "PC"}, {"id": "npc-a", "entity_type": "NPC"}],
        encounter={"id": "enc-1"},
        active_slot={"entity_id": "pc-a"},
    )

    assert next(a for a in actions if a.action == "attack").enabled is True
    assert next(a for a in actions if a.action == "end_turn").enabled is True


def test_spatial_visibility_requires_same_map_and_radius():
    viewer = {
        "id": uuid.uuid4(),
        "current_map_id": "map-a",
        "public_sheet": {"x": 5, "y": 5, "perception_radius": 2},
    }
    inside = {
        "id": uuid.uuid4(),
        "entity_type": "NPC",
        "current_map_id": "map-a",
        "public_sheet": {"x": 7, "y": 5},
    }
    outside = {
        "id": uuid.uuid4(),
        "entity_type": "NPC",
        "current_map_id": "map-a",
        "public_sheet": {"x": 8, "y": 5},
    }
    other_map = {
        "id": uuid.uuid4(),
        "entity_type": "NPC",
        "current_map_id": "map-b",
        "public_sheet": {"x": 5, "y": 5},
    }

    assert is_spatially_visible([viewer], inside) is True
    assert is_spatially_visible([viewer], outside) is False
    assert is_spatially_visible([viewer], other_map) is False
