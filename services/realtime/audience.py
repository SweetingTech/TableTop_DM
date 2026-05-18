"""Audience resolution for realtime broadcasts."""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from shared.auth.principal import load_principal
from shared.db.connection import execute_one, execute_query


def _as_str_set(values: Iterable[object] | None) -> set[str]:
    return {str(v) for v in (values or []) if v}


def dm_principals(campaign_id: str) -> set[str]:
    rows = execute_query(
        """
        SELECT m.principal_id
        FROM state.campaign_members m
        JOIN state.principals p ON p.id = m.principal_id
        WHERE m.campaign_id = %s
          AND p.is_active = true
          AND (m.role = 'GM' OR p.principal_type = 'SYSTEM')
        """,
        (str(campaign_id),),
    )
    return {str(r["principal_id"]) for r in rows}


def party_principals(campaign_id: str) -> set[str]:
    rows = execute_query(
        """
        SELECT m.principal_id
        FROM state.campaign_members m
        JOIN state.principals p ON p.id = m.principal_id
        WHERE m.campaign_id = %s
          AND p.is_active = true
          AND m.role IN ('PLAYER', 'OBSERVER', 'GOD_OPERATOR')
        """,
        (str(campaign_id),),
    )
    return {str(r["principal_id"]) for r in rows}


def public_principals(campaign_id: str) -> set[str]:
    rows = execute_query(
        """
        SELECT principal_id
        FROM state.campaign_members
        WHERE campaign_id = %s
        """,
        (str(campaign_id),),
    )
    return {str(r["principal_id"]) for r in rows}


def spatial_principals(
    *,
    campaign_id: str,
    map_id: Optional[str],
    x: Optional[int],
    y: Optional[int],
) -> set[str]:
    from services.domain.maps.decoherence import audience_for_event

    audience = set(audience_for_event(
        campaign_id=uuid.UUID(str(campaign_id)),
        map_id=uuid.UUID(str(map_id)) if map_id else None,
        x=x,
        y=y,
    ))
    return audience - dm_principals(campaign_id)


def resolve_principal_audience(
    *,
    campaign_id: str,
    visibility: str,
    visible_to: Iterable[object] | None = None,
    map_id: Optional[str] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> tuple[set[str], str]:
    """Resolve non-DM principal rooms for an event.

    Order matters: explicit ledger visibility beats spatial inference.
    DM delivery is handled separately by the broadcaster via dm room.
    """
    visibility = (visibility or "public").lower()
    dms = dm_principals(campaign_id)

    if visibility == "dm_only":
        return set(), "dm_only"

    explicit = _as_str_set(visible_to)
    if explicit:
        return explicit - dms, "explicit_visible_to"

    if visibility == "principal_scoped":
        return set(), "principal_scoped_empty"

    if visibility == "spatial" and map_id and x is not None and y is not None:
        return spatial_principals(campaign_id=campaign_id, map_id=map_id, x=x, y=y), "spatial"

    if visibility == "party":
        return party_principals(campaign_id) - dms, "party"

    if visibility == "public":
        return public_principals(campaign_id) - dms, "public"

    return set(), f"unknown_visibility:{visibility}"


def validate_socket_join(
    *,
    campaign_id: str,
    principal_id: str,
    session_id: Optional[str] = None,
) -> dict:
    """Validate a client-requested room join and return join metadata."""
    try:
        campaign_uuid = uuid.UUID(str(campaign_id))
        principal_uuid = uuid.UUID(str(principal_id))
        session_uuid = uuid.UUID(str(session_id)) if session_id else None
    except (ValueError, TypeError):
        raise ValueError("invalid campaign_id, principal_id, or session_id")

    principal = load_principal(principal_uuid, campaign_uuid)
    if not principal or not principal.role:
        raise PermissionError("principal is not a campaign member")

    if session_uuid:
        row = execute_one(
            "SELECT campaign_id FROM state.sessions WHERE id = %s",
            (str(session_uuid),),
        )
        if not row:
            raise PermissionError("session not found")
        if str(row["campaign_id"]) != str(campaign_uuid):
            raise PermissionError("session does not belong to campaign")

    return {
        "campaign_id": str(campaign_uuid),
        "principal_id": str(principal_uuid),
        "session_id": str(session_uuid) if session_uuid else None,
        "role": str(principal.role.value if hasattr(principal.role, "value") else principal.role),
        "is_dm": principal.is_gm() or principal.is_system(),
    }

