"""Party decoherence — spatial event filtering.

The model: each entity has a ``current_map_id`` and an ``(x, y)`` position
inside ``public_sheet``. When an event happens at some grid coordinate on a
map, only PCs that are (a) on the same map AND (b) within their perception
radius should receive it in real time.

This module is the policy layer. Phase 6f adds the helpers; the WebSocket
broadcaster integration happens incrementally — for now, callers can ask
``audience_for_event(...)`` and route accordingly.
"""

import uuid
from typing import Optional

from shared.db.connection import execute_one, execute_query
from .perception import perception_radius


def audience_for_event(
    *,
    campaign_id: uuid.UUID,
    map_id: Optional[uuid.UUID],
    x: Optional[int],
    y: Optional[int],
) -> list[str]:
    """Return the principal_ids that should receive an event happening at
    (map_id, x, y) inside the given campaign.

    Rules:
    - If ``map_id`` is None or position is None, the event is global to the
      campaign (mode change, session lifecycle, etc.) — every principal in
      the campaign receives it.
    - Otherwise, only PCs on that map with their position within their
      perception radius (Chebyshev) qualify, and the principals controlling
      those PCs are in the audience.
    - GMs and SYSTEM principals always receive everything (they need the
      omniscient view to run the game).
    """
    members = execute_query(
        """
        SELECT m.principal_id, m.role, p.principal_type
        FROM state.campaign_members m
        JOIN state.principals p ON p.id = m.principal_id
        WHERE m.campaign_id = %s
        """,
        (str(campaign_id),),
    )
    if not members:
        return []

    audience: set[str] = set()
    for m in members:
        if m["role"] == "GM" or m["principal_type"] == "SYSTEM":
            audience.add(str(m["principal_id"]))

    if map_id is None or x is None or y is None:
        # Campaign-wide event — everyone in.
        return [str(m["principal_id"]) for m in members]

    # Pull controlled PCs and check spatial reach.
    pcs = execute_query(
        """
        SELECT id, controller_principal_id, current_map_id, public_sheet
        FROM state.entities
        WHERE campaign_id = %s AND entity_type = 'PC' AND status = 'ACTIVE'
        """,
        (str(campaign_id),),
    )
    for pc in pcs:
        if pc.get("controller_principal_id") is None:
            continue
        if str(pc.get("current_map_id") or "") != str(map_id):
            continue
        sheet = pc.get("public_sheet") or {}
        px, py = sheet.get("x"), sheet.get("y")
        if px is None or py is None:
            continue
        r = perception_radius(dict(pc))
        if max(abs(px - x), abs(py - y)) <= r:
            audience.add(str(pc["controller_principal_id"]))

    return sorted(audience)


def transition_entity_map(
    entity_id: uuid.UUID,
    new_map_id: uuid.UUID,
    *,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> dict:
    """Update an entity's current_map_id and optionally their (x, y).

    Returns the updated entity row. Validates that the destination map
    belongs to the entity's campaign.
    """
    entity = execute_one(
        "SELECT id, campaign_id, public_sheet FROM state.entities WHERE id = %s",
        (str(entity_id),),
    )
    if not entity:
        raise ValueError("entity not found")
    target_map = execute_one(
        "SELECT id, campaign_id FROM state.maps WHERE id = %s",
        (str(new_map_id),),
    )
    if not target_map:
        raise ValueError("target map not found")
    if str(target_map["campaign_id"]) != str(entity["campaign_id"]):
        raise ValueError("target map belongs to a different campaign")

    if x is not None and y is not None:
        sheet = dict(entity.get("public_sheet") or {})
        sheet["x"] = int(x)
        sheet["y"] = int(y)
        import json as _json
        row = execute_one(
            "UPDATE state.entities SET current_map_id = %s, public_sheet = %s::jsonb, "
            "updated_at = now() WHERE id = %s RETURNING *",
            (str(new_map_id), _json.dumps(sheet), str(entity_id)),
        )
    else:
        row = execute_one(
            "UPDATE state.entities SET current_map_id = %s, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (str(new_map_id), str(entity_id)),
        )
    return dict(row)
