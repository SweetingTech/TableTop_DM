import os
import re
import struct
from shared.schemas.events import RollResult


def crypto_randint(low: int, high: int) -> int:
    span = high - low + 1
    return low + int.from_bytes(os.urandom(4), "big") % span


def roll_dice(notation: str, modifier: int = 0) -> RollResult:
    match = re.match(r"^(\d+)d(\d+)$", notation.strip().lower())
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")

    count = int(match.group(1))
    sides = int(match.group(2))

    if count < 1 or count > 100:
        raise ValueError(f"Dice count must be 1-100, got {count}")
    if sides < 2 or sides > 100:
        raise ValueError(f"Dice sides must be 2-100, got {sides}")

    rolls = [crypto_randint(1, sides) for _ in range(count)]
    raw_total = sum(rolls)
    total = raw_total + modifier

    parts = " + ".join(str(r) for r in rolls)
    breakdown = f"[{parts}]"
    if modifier != 0:
        sign = "+" if modifier > 0 else ""
        breakdown += f" {sign}{modifier}"
    breakdown += f" = {total}"

    return RollResult(
        dice=notation,
        rolls=rolls,
        modifier=modifier,
        total=total,
        breakdown=breakdown,
    )


def roll_d20(modifier: int = 0) -> RollResult:
    return roll_dice("1d20", modifier)


def roll_advantage(modifier: int = 0) -> RollResult:
    r1 = crypto_randint(1, 20)
    r2 = crypto_randint(1, 20)
    best = max(r1, r2)
    total = best + modifier
    return RollResult(
        dice="2d20kh1",
        rolls=[r1, r2],
        modifier=modifier,
        total=total,
        breakdown=f"[{r1}, {r2}] keep highest({best}) + {modifier} = {total}",
    )


def roll_disadvantage(modifier: int = 0) -> RollResult:
    r1 = crypto_randint(1, 20)
    r2 = crypto_randint(1, 20)
    worst = min(r1, r2)
    total = worst + modifier
    return RollResult(
        dice="2d20kl1",
        rolls=[r1, r2],
        modifier=modifier,
        total=total,
        breakdown=f"[{r1}, {r2}] keep lowest({worst}) + {modifier} = {total}",
    )
