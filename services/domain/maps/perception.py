"""Perception radius logic for POI discovery.

A character's class determines how far around them POIs become visible. This
is a real game mechanic per the design doc — ranger/scout-type classes see
much further than melee bruisers, who have to actively search.

Lookup is intentionally hardcoded for now. A future migration can move it to
state.classes or per-entity overrides; the call site won't change.
"""

import uuid
from typing import Optional

# Tiles. Chebyshev distance (king-move) so 4 = 9x9 area centered on the entity.
CLASS_RADIUS = {
    "ranger": 5,
    "scout": 5,
    "rogue": 4,
    "wizard": 4,
    "sorcerer": 4,
    "druid": 4,
    "cleric": 3,
    "bard": 3,
    "barbarian": 2,
    "fighter": 2,
    "paladin": 2,
    "monk": 3,
}
DEFAULT_RADIUS = 3


def perception_radius(entity: dict) -> int:
    """Return the entity's POI-discovery radius in tiles.

    Reads (in priority order):
      1. entity.public_sheet.perception_radius (explicit override)
      2. entity.public_sheet.class             (looked up in CLASS_RADIUS)
      3. DEFAULT_RADIUS
    """
    sheet = entity.get("public_sheet") or {}
    explicit = sheet.get("perception_radius")
    if isinstance(explicit, (int, float)):
        return max(0, int(explicit))
    cls = (sheet.get("class") or "").strip().lower()
    return CLASS_RADIUS.get(cls, DEFAULT_RADIUS)


def discovered_pois(entity: dict, pois: list[dict]) -> list[dict]:
    """Filter the POI list down to ones inside the entity's perception range.

    Uses Chebyshev distance: a 5-tile radius covers an 11×11 square centered
    on the entity, which matches how grid-based RPGs typically draw vision.
    """
    sheet = entity.get("public_sheet") or {}
    ex, ey = sheet.get("x"), sheet.get("y")
    if ex is None or ey is None:
        return []
    r = perception_radius(entity)
    out = []
    for poi in pois:
        if max(abs(poi["x"] - ex), abs(poi["y"] - ey)) <= r:
            out.append(poi)
    return out
