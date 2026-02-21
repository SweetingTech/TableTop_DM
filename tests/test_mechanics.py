import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mechanics.dice import roll_dice, roll_d20, roll_advantage, roll_disadvantage
from services.mechanics.engine import MechanicsEngine
from services.spatial.engine import SpatialEngine, GridCell
from services.domain.content_rating.gate import ContentRatingGate
from shared.schemas.enums import ContentRating
import uuid


def test_dice_roll():
    result = roll_dice("2d6", 3)
    assert len(result.rolls) == 2
    assert all(1 <= r <= 6 for r in result.rolls)
    assert result.total == sum(result.rolls) + 3
    assert result.modifier == 3
    print(f"  dice roll: {result.breakdown}")


def test_d20():
    result = roll_d20(5)
    assert len(result.rolls) == 1
    assert 1 <= result.rolls[0] <= 20
    assert result.total == result.rolls[0] + 5
    print(f"  d20: {result.breakdown}")


def test_advantage():
    result = roll_advantage(3)
    assert len(result.rolls) == 2
    best = max(result.rolls)
    assert result.total == best + 3
    print(f"  advantage: {result.breakdown}")


def test_disadvantage():
    result = roll_disadvantage(2)
    assert len(result.rolls) == 2
    worst = min(result.rolls)
    assert result.total == worst + 2
    print(f"  disadvantage: {result.breakdown}")


def test_update_hp():
    engine = MechanicsEngine()
    eid = uuid.uuid4()
    result = engine.update_hp(eid, -5, 20, 20, "test")
    assert result.result["hp_current"] == 15
    assert result.result["is_down"] == False
    print(f"  update_hp: {result.result}")


def test_update_hp_clamp():
    engine = MechanicsEngine()
    eid = uuid.uuid4()
    result = engine.update_hp(eid, -100, 20, 20, "overkill")
    assert result.result["hp_current"] == 0
    assert result.result["is_down"] == True
    print(f"  update_hp clamp: {result.result}")


def test_update_hp_overheal():
    engine = MechanicsEngine()
    eid = uuid.uuid4()
    result = engine.update_hp(eid, 100, 15, 20, "heal")
    assert result.result["hp_current"] == 20
    print(f"  update_hp overheal: {result.result}")


def test_resolve_attack():
    engine = MechanicsEngine()
    aid = uuid.uuid4()
    tid = uuid.uuid4()
    result = engine.resolve_attack(aid, tid, 5, 15, "1d8", 3, "longsword",
                                   target_hp=20, target_max_hp=20)
    print(f"  attack: hits={result.result['hits']}, damage={result.result['damage']}")
    assert isinstance(result.result["hits"], bool)


def test_resolve_save():
    engine = MechanicsEngine()
    eid = uuid.uuid4()
    result = engine.resolve_save(eid, 3, 15, "DEX", "PRONE", "2d6",
                                  half_on_save=True, entity_hp=20, entity_max_hp=20)
    print(f"  save: success={result.result['success']}, damage={result.result['damage']}")


def test_spatial_pathfinding():
    engine = SpatialEngine()
    cells = []
    for x in range(5):
        for y in range(5):
            walkable = not (x == 2 and y in (1, 2, 3))
            cells.append({"x": x, "y": y,
                          "collision_mask": "0" * 16 if walkable else "1" + "0" * 15,
                          "terrain": {}})
    engine.load_grid("test_map", cells)

    path = engine.compute_path("test_map", 0, 2, 4, 2)
    assert path is not None
    assert path[0] == (0, 2)
    assert path[-1] == (4, 2)
    assert (2, 2) not in path
    print(f"  pathfinding: path length={len(path)}, path={path}")


def test_spatial_los():
    engine = SpatialEngine()
    cells = []
    for x in range(5):
        for y in range(5):
            walkable = not (x == 2 and y == 2)
            cells.append({"x": x, "y": y,
                          "collision_mask": "0" * 16 if walkable else "1" + "0" * 15,
                          "terrain": {}})
    engine.load_grid("los_map", cells)

    los_clear = engine.check_line_of_sight("los_map", 0, 0, 4, 4)
    print(f"  LoS clear: {los_clear['clear']}, blockers: {los_clear['blockers']}")

    los_blocked = engine.check_line_of_sight("los_map", 0, 2, 4, 2)
    print(f"  LoS blocked: {los_blocked['clear']}, blockers: {los_blocked['blockers']}")


def test_spatial_threat():
    engine = SpatialEngine()
    assert engine.check_threat_radius("m", 5, 5, 5, 6, radius=1) == True
    assert engine.check_threat_radius("m", 5, 5, 7, 7, radius=1) == False
    print("  threat radius: passed")


def test_content_rating_safe():
    gate = ContentRatingGate(ContentRating.SAFE)
    ok = gate.check_content("The knight raises his sword")
    assert ok["allowed"] == True

    blocked = gate.check_content("gruesome torture scene")
    assert blocked["allowed"] == False
    print(f"  content gate SAFE: pass")


def test_content_rating_hard_block():
    gate = ContentRatingGate(ContentRating.EXPLICIT)
    blocked = gate.check_content("non-consensual sexual content")
    assert blocked["allowed"] == False
    assert blocked["category"] == "HARD_BLOCK"
    print(f"  content gate HARD_BLOCK: pass")


if __name__ == "__main__":
    tests = [
        ("Dice Roll", test_dice_roll),
        ("D20 Roll", test_d20),
        ("Advantage", test_advantage),
        ("Disadvantage", test_disadvantage),
        ("Update HP", test_update_hp),
        ("Update HP Clamp", test_update_hp_clamp),
        ("Update HP Overheal", test_update_hp_overheal),
        ("Resolve Attack", test_resolve_attack),
        ("Resolve Save", test_resolve_save),
        ("Spatial Pathfinding", test_spatial_pathfinding),
        ("Spatial Line of Sight", test_spatial_los),
        ("Spatial Threat Radius", test_spatial_threat),
        ("Content Rating SAFE", test_content_rating_safe),
        ("Content Rating Hard Block", test_content_rating_hard_block),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
            print(f"  PASS: {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL: {name} - {e}")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed > 0:
        exit(1)
