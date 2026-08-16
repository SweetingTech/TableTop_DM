import pytest
from services.mechanics.dice import roll_dice, roll_d20, roll_advantage, roll_disadvantage

pytestmark = pytest.mark.unit

def test_roll_dice_basic():
    result = roll_dice("1d6")
    assert result.dice == "1d6"
    assert len(result.rolls) == 1
    assert 1 <= result.rolls[0] <= 6
    assert result.total == result.rolls[0]
    assert result.modifier == 0
    assert f"[{result.rolls[0]}] = {result.total}" in result.breakdown

def test_roll_dice_multiple():
    result = roll_dice("3d10", modifier=5)
    assert result.dice == "3d10"
    assert len(result.rolls) == 3
    for r in result.rolls:
        assert 1 <= r <= 10
    assert result.total == sum(result.rolls) + 5
    assert result.modifier == 5
    expected_breakdown_start = f"[{' + '.join(str(r) for r in result.rolls)}]"
    assert result.breakdown.startswith(expected_breakdown_start)
    assert f"+5 = {result.total}" in result.breakdown

def test_roll_dice_negative_modifier():
    result = roll_dice("1d20", modifier=-2)
    assert result.modifier == -2
    assert result.total == result.rolls[0] - 2
    assert f"-2 = {result.total}" in result.breakdown

def test_roll_dice_notation_parsing():
    # Case insensitivity and whitespace
    assert roll_dice(" 2D4 ").dice == " 2D4 "
    assert len(roll_dice("2d4").rolls) == 2

def test_roll_dice_invalid_notation():
    with pytest.raises(ValueError, match="Invalid dice notation"):
        roll_dice("invalid")
    with pytest.raises(ValueError, match="Invalid dice notation"):
        roll_dice("d6")
    with pytest.raises(ValueError, match="Invalid dice notation"):
        roll_dice("1d")

def test_roll_dice_bounds_count():
    with pytest.raises(ValueError, match="Dice count must be 1-100"):
        roll_dice("0d6")
    with pytest.raises(ValueError, match="Dice count must be 1-100"):
        roll_dice("101d6")
    # Boundary cases
    assert len(roll_dice("1d6").rolls) == 1
    assert len(roll_dice("100d6").rolls) == 100

def test_roll_dice_bounds_sides():
    with pytest.raises(ValueError, match="Dice sides must be 2-100"):
        roll_dice("1d1")
    with pytest.raises(ValueError, match="Dice sides must be 2-100"):
        roll_dice("1d101")
    # Boundary cases
    assert 1 <= roll_dice("1d2").rolls[0] <= 2
    assert 1 <= roll_dice("1d100").rolls[0] <= 100

def test_roll_d20():
    result = roll_d20(2)
    assert result.dice == "1d20"
    assert len(result.rolls) == 1
    assert result.total == result.rolls[0] + 2

def test_roll_advantage():
    result = roll_advantage(4)
    assert result.dice == "2d20kh1"
    assert len(result.rolls) == 2
    best = max(result.rolls)
    assert result.total == best + 4
    assert f"keep highest({best})" in result.breakdown

def test_roll_disadvantage():
    result = roll_disadvantage(-1)
    assert result.dice == "2d20kl1"
    assert len(result.rolls) == 2
    worst = min(result.rolls)
    assert result.total == worst - 1
    assert f"keep lowest({worst})" in result.breakdown
