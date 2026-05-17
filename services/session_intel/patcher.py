"""Story-state patcher (Phase 36).

Once a proposed_story_patches row is APPROVED, this module applies it to
state.story_state and (in the future) related continuity surfaces.

The dispatcher table maps event_type → the story_state field(s) that get
updated. Anything not in the table is recorded as a story_state event but
doesn't modify the structured fields — the DM-only notes catch interpretive
items that aren't yet first-class.

Apply is transactional: the patch row is marked APPLIED with the
resulting ledger event id in `applied_event_id`. If the patch can't be
applied for any reason, the transaction rolls back and the patch stays
APPROVED so the DM can retry / edit / reject.
"""

import json
import logging
import uuid
from typing import Any

from shared.db.connection import get_connection, execute_one


log = logging.getLogger(__name__)


class PatchError(Exception):
    """Anything that goes wrong applying an approved patch."""


def _get_or_create_story_state(conn, campaign_id: str, session_id: str) -> dict:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM state.story_state WHERE session_id = %s",
        (session_id,),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='state' AND table_name='story_state' ORDER BY ordinal_position"
        )
        cols = [r[0] for r in cur.fetchall()]
        cur.close()
        return dict(zip(cols, row))
    cur.execute(
        "INSERT INTO state.story_state (campaign_id, session_id) VALUES (%s, %s) RETURNING *",
        (campaign_id, session_id),
    )
    row = cur.fetchone()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='state' AND table_name='story_state' ORDER BY ordinal_position"
    )
    cols = [r[0] for r in cur.fetchall()]
    cur.close()
    return dict(zip(cols, row))


def _append_jsonb_list(conn, session_id: str, field: str, item: dict):
    """Append `item` to a JSONB-array field on story_state, idempotent
    against exact-duplicate items (cheap dedupe)."""
    cur = conn.cursor()
    cur.execute(
        f"SELECT {field} FROM state.story_state WHERE session_id = %s FOR UPDATE",
        (session_id,),
    )
    existing = cur.fetchone()
    arr = list(existing[0] or []) if existing else []
    if item not in arr:
        arr.append(item)
    cur.execute(
        f"UPDATE state.story_state SET {field} = %s::jsonb, updated_at = now() "
        f"WHERE session_id = %s",
        (json.dumps(arr), session_id),
    )
    cur.close()


def _set_scalar(conn, session_id: str, field: str, value: Any):
    cur = conn.cursor()
    cur.execute(
        f"UPDATE state.story_state SET {field} = %s, updated_at = now() "
        f"WHERE session_id = %s",
        (value, session_id),
    )
    cur.close()


def _append_dm_note(conn, session_id: str, note: str):
    cur = conn.cursor()
    cur.execute(
        "UPDATE state.story_state SET dm_notes = COALESCE(dm_notes, '') || %s, "
        "updated_at = now() WHERE session_id = %s",
        (("\n" if note else "") + note, session_id),
    )
    cur.close()


# ---------------------------------------------------------------------
# Dispatch table — event_type → field-of-story_state-affected
# ---------------------------------------------------------------------

def _apply_event(conn, patch: dict):
    event_type = patch["event_type"]
    session_id = patch["session_id"]
    delta = patch.get("patch") or {}
    summary = patch.get("summary") or ""

    if event_type == "location_changed":
        loc = delta.get("current_location") or delta.get("location")
        if loc:
            _set_scalar(conn, session_id, "current_location", loc)

    elif event_type == "scene_started":
        _append_jsonb_list(conn, session_id, "recent_events",
                           {"kind": "scene_started", "summary": summary, "at": delta})

    elif event_type == "scene_ended":
        _append_jsonb_list(conn, session_id, "recent_events",
                           {"kind": "scene_ended", "summary": summary})

    elif event_type in ("npc_introduced", "npc_updated", "npc_attitude_changed"):
        _append_jsonb_list(conn, session_id, "active_npcs",
                           {"kind": event_type, "summary": summary, **delta})

    elif event_type in ("quest_introduced", "quest_updated"):
        _append_jsonb_list(conn, session_id, "active_quests",
                           {"kind": event_type, "summary": summary, **delta})

    elif event_type in ("unresolved_thread", "promise_made", "threat_created", "consequence_created"):
        _append_jsonb_list(conn, session_id, "plot_threads",
                           {"kind": event_type, "summary": summary, **delta})

    elif event_type == "loot_gained":
        _append_jsonb_list(conn, session_id, "party_resources",
                           {"kind": "loot", "summary": summary, **delta})

    elif event_type == "item_used":
        _append_jsonb_list(conn, session_id, "recent_events",
                           {"kind": "item_used", "summary": summary, **delta})

    elif event_type == "secret_revealed":
        # Visibility decides where this goes. Public/party → recent_events;
        # dm_only → dm_notes (private DM track).
        if patch.get("visibility") == "dm_only":
            _append_dm_note(conn, session_id, f"[SECRET] {summary}")
        else:
            _append_jsonb_list(conn, session_id, "recent_events",
                               {"kind": "secret_revealed", "summary": summary})

    elif event_type == "retcon_or_contradiction":
        # Never auto-applied; surfaced for DM resolution only.
        _append_dm_note(conn, session_id, f"[CONTRADICTION FLAGGED] {summary}")

    else:
        # Unknown event_type — keep it in dm_notes so nothing is silently lost.
        _append_dm_note(conn, session_id, f"[UNHANDLED {event_type}] {summary}")


def apply_patch(patch_id: uuid.UUID, *, reviewed_by: uuid.UUID = None) -> dict:
    """Commit an APPROVED patch to story_state. Idempotent — already-APPLIED
    patches return the existing applied_event_id."""
    patch = execute_one(
        "SELECT * FROM state.proposed_story_patches WHERE id = %s",
        (str(patch_id),),
    )
    if not patch:
        raise PatchError(f"Patch {patch_id} not found")
    if patch["status"] == "APPLIED":
        return {"already_applied": True, "applied_event_id": patch.get("applied_event_id")}
    if patch["status"] not in ("APPROVED", "EDITED"):
        raise PatchError(
            f"Patch {patch_id} is {patch['status']}; only APPROVED or EDITED patches can apply"
        )

    conn = get_connection()
    try:
        _get_or_create_story_state(conn, patch["campaign_id"], patch["session_id"])
        _apply_event(conn, dict(patch))
        cur = conn.cursor()
        cur.execute(
            "UPDATE state.proposed_story_patches SET status = 'APPLIED', "
            "reviewed_at = now(), reviewed_by = COALESCE(%s, reviewed_by) "
            "WHERE id = %s",
            (str(reviewed_by) if reviewed_by else None, str(patch_id)),
        )
        cur.close()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"applied": True, "patch_id": str(patch_id)}
