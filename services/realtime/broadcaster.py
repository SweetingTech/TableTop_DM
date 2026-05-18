"""Single realtime broadcast router.

All game-state WebSocket delivery should pass through this module so
visibility and spatial decoherence are enforced consistently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Literal, Optional

from .audience import resolve_principal_audience
from .rooms import campaign_public_room, dm_room, principal_room


VisibilityScope = Literal["public", "party", "dm_only", "principal_scoped", "spatial"]
LOGGER = logging.getLogger(__name__)


@dataclass
class BroadcastEnvelope:
    event_id: str
    campaign_id: str
    session_id: Optional[str]
    event_type: str
    payload: dict[str, Any]
    visibility: VisibilityScope = "public"
    visible_to: list[str] = field(default_factory=list)
    map_id: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    include_dm: bool = True


_socketio = None


def configure_socketio(socketio) -> None:
    global _socketio
    _socketio = socketio


def _event_name(event_type: str) -> str:
    if event_type in {"game_event", "turn_advanced"}:
        return event_type
    return "game_event"


def _payload_for(envelope: BroadcastEnvelope, *, scope: str, reason: str, room: str) -> dict[str, Any]:
    payload = dict(envelope.payload or {})
    payload.setdefault("event_id", str(envelope.event_id))
    payload.setdefault("event_type", envelope.event_type)
    if payload.get("visibility") and payload.get("visibility") != envelope.visibility:
        LOGGER.warning(
            "broadcast payload visibility %r overridden by canonical envelope visibility %r",
            payload.get("visibility"),
            envelope.visibility,
        )
    payload["visibility"] = envelope.visibility
    payload["delivery"] = {
        "scope": scope,
        "reason": reason,
        "room": room,
    }
    if envelope.session_id:
        payload.setdefault("session_id", str(envelope.session_id))
    payload.setdefault("campaign_id", str(envelope.campaign_id))
    return payload


def broadcast_game_event(envelope: BroadcastEnvelope, *, socketio=None) -> list[dict[str, str]]:
    """Emit an envelope to the rooms allowed by its visibility.

    Returns delivery records for tests and optional diagnostics.
    """
    sio = socketio or _socketio
    if sio is None:
        raise RuntimeError("SocketIO is not configured for realtime broadcaster")

    event_name = _event_name(envelope.event_type)
    deliveries: list[dict[str, str]] = []

    principals, reason = resolve_principal_audience(
        campaign_id=str(envelope.campaign_id),
        visibility=envelope.visibility,
        visible_to=envelope.visible_to,
        map_id=envelope.map_id,
        x=envelope.x,
        y=envelope.y,
    )

    if envelope.visibility == "public" and not envelope.visible_to:
        room = campaign_public_room(str(envelope.campaign_id))
        sio.emit(event_name, _payload_for(envelope, scope="public", reason="public_campaign", room=room), room=room)
        deliveries.append({"event": event_name, "room": room, "scope": "public", "reason": "public_campaign"})
    else:
        for principal_id in sorted(principals):
            room = principal_room(principal_id)
            sio.emit(event_name, _payload_for(envelope, scope=envelope.visibility, reason=reason, room=room), room=room)
            deliveries.append({"event": event_name, "room": room, "scope": envelope.visibility, "reason": reason})

    if envelope.include_dm:
        room = dm_room(str(envelope.campaign_id))
        sio.emit(event_name, _payload_for(envelope, scope="dm", reason="dm_receives_all", room=room), room=room)
        deliveries.append({"event": event_name, "room": room, "scope": "dm", "reason": "dm_receives_all"})

    return deliveries


def envelope_from_event(event: Any, *, visibility: VisibilityScope | None = None) -> BroadcastEnvelope:
    """Create a broadcast envelope from an EventEnvelope-like object."""
    data = event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)
    payload = data.get("payload") or data
    visible_to = [str(v) for v in (data.get("visible_to") or [])]
    inferred_visibility: VisibilityScope = visibility or ("principal_scoped" if visible_to else "public")
    return BroadcastEnvelope(
        event_id=str(data.get("event_id") or data.get("id") or ""),
        campaign_id=str(data["campaign_id"]),
        session_id=str(data.get("session_id")) if data.get("session_id") else None,
        event_type=str(data.get("type") or data.get("event_type") or "game_event"),
        payload=payload,
        visibility=inferred_visibility,
        visible_to=visible_to,
        map_id=payload.get("map_id") or payload.get("current_map_id"),
        x=payload.get("x"),
        y=payload.get("y"),
    )
