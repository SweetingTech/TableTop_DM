from __future__ import annotations

import uuid

from flask import jsonify, request

from services.api.local_identity import (
    strict_join_tokens_required,
    validate_join_token,
)


def principal_id_from_request():
    data = request.get_json(silent=True) or {}
    return (
        request.args.get("principal_id")
        or request.headers.get("X-Principal-Id")
        or request.headers.get("X-TTDM-Principal-Id")
        or data.get("principal_id")
    )


def join_token_from_request():
    data = request.get_json(silent=True) or {}
    return (
        request.args.get("join_token")
        or request.args.get("invite_token")
        or request.headers.get("X-Join-Token")
        or request.headers.get("X-TTDM-Join-Token")
        or data.get("join_token")
        or data.get("invite_token")
    )


def require_campaign_principal(campaign_id):
    from shared.auth.principal import load_principal

    principal_id = principal_id_from_request()
    if not principal_id:
        return None, (jsonify({"error": "principal_id is required"}), 401)

    try:
        campaign_uuid = uuid.UUID(str(campaign_id))
        principal_uuid = uuid.UUID(str(principal_id))
    except (ValueError, TypeError):
        return None, (jsonify({"error": "invalid campaign_id or principal_id"}), 400)

    principal = load_principal(principal_uuid, campaign_uuid)
    if not principal or not principal.role:
        return None, (jsonify({"error": "principal is not a campaign member"}), 403)

    return principal, None


def session_record(session_id):
    from shared.db.connection import execute_one

    try:
        session_uuid = uuid.UUID(str(session_id))
    except (ValueError, TypeError):
        return None, (jsonify({"error": "invalid session_id"}), 400)

    row = execute_one(
        "SELECT * FROM state.sessions WHERE id = %s", (str(session_uuid),)
    )
    if not row:
        return None, (jsonify({"error": "session not found"}), 404)
    return row, None


def require_session_principal(session_id):
    session, error = session_record(session_id)
    if error:
        return None, None, error
    principal, error = require_campaign_principal(str(session["campaign_id"]))
    if error:
        return None, session, error
    if strict_join_tokens_required():
        validation = validate_join_token(
            campaign_id=str(session["campaign_id"]),
            session_id=str(session["id"]),
            principal_id=str(principal.principal_id),
            role=str(principal.role),
            token=join_token_from_request(),
        )
        if not validation.ok:
            return None, session, (jsonify({"error": validation.reason}), 401)
    return principal, session, None


def require_campaign_gm(campaign_id, *, require_join_token: bool = False):
    principal, error = require_campaign_principal(campaign_id)
    if error:
        return None, error

    if not (principal.is_gm() or principal.is_system()):
        return None, (jsonify({"error": "GM or system principal required"}), 403)

    if require_join_token:
        supplied_token = join_token_from_request()
        validation = validate_join_token(
            campaign_id=str(campaign_id),
            session_id=None,
            principal_id=str(principal.principal_id),
            role=str(principal.role),
            token=supplied_token,
        )
        if not validation.ok:
            return None, (
                jsonify({"error": "validated local GM identity required"}),
                401,
            )

    return principal, None


def require_session_gm(session_id, *, require_join_token: bool = True):
    principal, session, error = require_session_principal(session_id)
    if error:
        return None, session, error
    if not (principal.is_gm() or principal.is_system()):
        return (
            None,
            session,
            (jsonify({"error": "GM or system principal required"}), 403),
        )
    if require_join_token:
        supplied_token = join_token_from_request()
        validation = validate_join_token(
            campaign_id=str(session["campaign_id"]),
            session_id=str(session["id"]),
            principal_id=str(principal.principal_id),
            role=str(principal.role),
            token=supplied_token,
        )
        if not validation.ok:
            return (
                None,
                session,
                (jsonify({"error": "validated local GM identity required"}), 401),
            )
    return principal, session, None


def require_entity_gm(entity_id, *, require_join_token: bool = True):
    from shared.db.connection import execute_one

    entity = execute_one(
        "SELECT id, campaign_id FROM state.entities WHERE id = %s", (entity_id,)
    )
    if not entity:
        return None, None, (jsonify({"error": "Not found"}), 404)
    principal, error = require_campaign_gm(
        str(entity["campaign_id"]), require_join_token=require_join_token
    )
    if error:
        return None, entity, error
    return principal, entity, None


def continuity_visibility_scope(principal, requested: str | None) -> str:
    requested = (requested or "").lower()
    if principal.is_gm() or principal.is_system():
        return (
            requested if requested in {"dm", "party", "principal", "public"} else "dm"
        )
    if requested == "public":
        return "public"
    if requested == "party":
        return "party"
    return "principal"


def redact_story_state(row):
    if not row:
        return row
    from services.api.responses import serialize

    data = serialize(dict(row))
    data.pop("dm_notes", None)
    data.pop("dm_private_notes", None)
    if isinstance(data.get("active_npcs"), list):
        data["active_npcs"] = [
            {
                k: v
                for k, v in npc.items()
                if k not in {"notes", "secret", "secrets", "dm_notes"}
            }
            if isinstance(npc, dict)
            else npc
            for npc in data["active_npcs"]
        ]
    return data
