from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared.db.connection import execute_one, execute_query


def strict_join_tokens_required() -> bool:
    return os.environ.get("TTDM_REQUIRE_JOIN_TOKEN", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def smoke_join_tokens_allowed() -> bool:
    return os.environ.get("TTDM_ALLOW_SMOKE_JOIN_TOKENS", "1").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def expected_local_join_token(principal_id: str, role: str | None) -> str:
    prefix = "dm" if str(role or "").upper() == "GM" else "player"
    return f"{prefix}-smoke-join-{principal_id}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JoinCodeValidation:
    ok: bool
    reason: str | None = None


def validate_join_token(
    *,
    campaign_id: str,
    principal_id: str,
    role: str | None,
    token: str | None,
    session_id: str | None = None,
) -> JoinCodeValidation:
    if not token:
        return JoinCodeValidation(False, "join token required")

    if smoke_join_tokens_allowed() and token == expected_local_join_token(
        principal_id, role
    ):
        return JoinCodeValidation(True)

    row = execute_one(
        """
        SELECT id, expires_at
        FROM state.local_join_codes
        WHERE campaign_id = %s
          AND principal_id = %s
          AND token_hash = %s
          AND revoked_at IS NULL
          AND (session_id IS NULL OR session_id = %s)
        ORDER BY session_id NULLS LAST, created_at DESC
        LIMIT 1
        """,
        (campaign_id, principal_id, token_hash(token), session_id),
    )
    if not row:
        return JoinCodeValidation(False, "invalid join token")
    expires_at = row.get("expires_at")
    if expires_at and expires_at <= datetime.now(UTC):
        return JoinCodeValidation(False, "join token expired")
    return JoinCodeValidation(True)


def create_join_code(
    *,
    campaign_id: str,
    principal_id: str,
    created_by: str,
    session_id: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    token = f"ttdm-{secrets.token_urlsafe(18)}"
    row = execute_one(
        """
        INSERT INTO state.local_join_codes (
            campaign_id, session_id, principal_id, token_hash, label, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, campaign_id, session_id, principal_id, label, created_by,
                  created_at, expires_at, revoked_at
        """,
        (campaign_id, session_id, principal_id, token_hash(token), label, created_by),
    )
    data = dict(row)
    data["join_token"] = token
    data["join_url"] = f"/game?principal_id={principal_id}&join_token={token}"
    return data


def list_join_codes(campaign_id: str) -> list[dict[str, Any]]:
    rows = execute_query(
        """
        SELECT jc.id, jc.campaign_id, jc.session_id, jc.principal_id, jc.label,
               jc.created_by, jc.created_at, jc.expires_at, jc.revoked_at,
               p.display_name, cm.role
        FROM state.local_join_codes jc
        JOIN state.principals p ON p.id = jc.principal_id
        LEFT JOIN state.campaign_members cm
          ON cm.campaign_id = jc.campaign_id AND cm.principal_id = jc.principal_id
        WHERE jc.campaign_id = %s
        ORDER BY jc.created_at DESC
        """,
        (campaign_id,),
    )
    return [dict(row) for row in rows]


def revoke_join_code(*, campaign_id: str, code_id: str) -> dict[str, Any] | None:
    try:
        uuid.UUID(str(code_id))
    except (TypeError, ValueError):
        return None
    return execute_one(
        """
        UPDATE state.local_join_codes
        SET revoked_at = COALESCE(revoked_at, now())
        WHERE id = %s AND campaign_id = %s
        RETURNING id, campaign_id, principal_id, revoked_at
        """,
        (code_id, campaign_id),
    )
