from __future__ import annotations

import uuid

from services.domain.maps.perception import discovered_pois, perception_radius
from shared.auth.principal import PrincipalContext
from shared.db.connection import execute_query

from .serializers import row_dict, serialize


def _position(entity: dict) -> tuple[int | None, int | None]:
    sheet = entity.get("public_sheet") or {}
    return sheet.get("x"), sheet.get("y")


def is_spatially_visible(viewers: list[dict], entity: dict) -> bool:
    if not viewers:
        return False
    if entity.get("entity_type") == "PC" and any(
        str(v["id"]) == str(entity["id"]) for v in viewers
    ):
        return True

    entity_map = str(entity.get("current_map_id") or "")
    ex, ey = _position(entity)
    if not entity_map or ex is None or ey is None:
        return False

    for viewer in viewers:
        if str(viewer.get("current_map_id") or "") != entity_map:
            continue
        vx, vy = _position(viewer)
        if vx is None or vy is None:
            continue
        if max(abs(int(vx) - int(ex)), abs(int(vy) - int(ey))) <= perception_radius(
            viewer
        ):
            return True
    return False


def visible_entities(
    *,
    campaign_id: uuid.UUID,
    principal: PrincipalContext,
    controlled_entities: list[dict],
    conn=None,
) -> list[dict]:
    rows = execute_query(
        """
        SELECT id, campaign_id, entity_type, name, tags, public_sheet, hp_current,
               hp_max, ac, speed, controlled_by, controller_principal_id,
               current_map_id, image_url, status
        FROM state.entities
        WHERE campaign_id = %s AND status = 'ACTIVE'
        ORDER BY entity_type, name
        """,
        (str(campaign_id),),
        conn=conn,
    )
    if principal.is_gm() or principal.is_system():
        return [row_dict(r) for r in rows]
    return [
        row_dict(r) for r in rows if is_spatially_visible(controlled_entities, dict(r))
    ]


def visible_pois(controlled_entities: list[dict], *, conn=None) -> list[dict]:
    out: dict[str, dict] = {}
    for entity in controlled_entities:
        map_id = entity.get("current_map_id")
        if not map_id:
            continue
        pois = execute_query(
            "SELECT * FROM state.map_pois WHERE map_id = %s",
            (str(map_id),),
            conn=conn,
        )
        for poi in discovered_pois(entity, [dict(p) for p in pois]):
            if poi.get("is_hidden"):
                continue
            out[str(poi["id"])] = row_dict(poi)
    return list(out.values())


def visible_decorations(controlled_entities: list[dict], *, conn=None) -> list[dict]:
    map_ids = sorted(
        {
            str(e.get("current_map_id"))
            for e in controlled_entities
            if e.get("current_map_id")
        }
    )
    if not map_ids:
        return []
    rows = execute_query(
        "SELECT * FROM state.map_decorations WHERE map_id = ANY(%s::uuid[]) ORDER BY map_id, y, x",
        (map_ids,),
        conn=conn,
    )
    return [row_dict(r) for r in rows]


def visible_recent_events(
    *,
    session_id: uuid.UUID,
    principal_id: uuid.UUID,
    limit: int,
    conn=None,
) -> tuple[list[dict], dict]:
    rows = execute_query(
        """
        SELECT seq_id, event_id, type, sender_principal_id, sender_entity_id,
               payload, visible_to, domain_tags, created_at
        FROM ledger.session_ledger
        WHERE session_id = %s AND %s = ANY(visible_to)
        ORDER BY seq_id DESC
        LIMIT %s
        """,
        (str(session_id), str(principal_id), int(limit)),
        conn=conn,
    )
    ordered = [row_dict(r) for r in reversed(rows)]
    last = ordered[-1] if ordered else None
    cursor = {
        "last_ledger_id": last.get("event_id") if last else None,
        "last_sequence": last.get("seq_id") if last else None,
    }
    return serialize(ordered), cursor
