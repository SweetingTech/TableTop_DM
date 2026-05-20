"""Continuity queries (Phase 38).

Surface the "what should resurface next session" view of the patch log.
All read-only — these endpoints don't write anything; they're filtered
projections of state.proposed_story_patches and state.story_state.

Each query is intentionally simple. The data model is already where the
intelligence lives — these are just convenience SQL.
"""

import uuid

from shared.db.connection import execute_query
from services.session_intel.rag_context import attach_sources


def _visibility_filter(visibility: str) -> list[str]:
    filters = {
        "dm": ["public", "party", "dm_only", "principal_scoped"],
        "party": ["public", "party"],
        "principal": ["public", "party", "principal_scoped"],
        "public": ["public"],
    }
    return filters.get(visibility, filters["dm"])


def _principal_scoped_clause(principal_id: str | None) -> tuple[str, list[str]]:
    if principal_id is None:
        return "", []
    return (
        """
          AND (
            visibility <> 'principal_scoped'
            OR COALESCE(patch->'visible_to', '[]'::jsonb) ? %s
          )
        """,
        [str(principal_id)],
    )


def open_threads(
    campaign_id: uuid.UUID,
    visibility: str = "dm",
    *,
    principal_id: str | None = None,
    conn=None,
) -> list[dict]:
    """Plot threads that haven't been resolved yet. A thread is 'open'
    if it has an APPLIED unresolved_thread/promise/threat/consequence
    patch and no later APPLIED patch references it as resolved."""
    scoped_clause, scoped_params = _principal_scoped_clause(principal_id)
    rows = execute_query(
        f"""
        SELECT id, session_id, event_type, summary, entities, patch, evidence,
               visibility, confidence, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND status = 'APPLIED'
          AND visibility = ANY(%s)
          {scoped_clause}
          AND event_type IN ('unresolved_thread', 'promise_made',
                             'threat_created', 'consequence_created')
        ORDER BY created_at DESC
        """,
        (str(campaign_id), _visibility_filter(visibility), *scoped_params),
        conn=conn,
    )
    return [attach_sources(dict(r)) for r in rows]


def unresolved_promises(
    campaign_id: uuid.UUID,
    visibility: str = "dm",
    *,
    principal_id: str | None = None,
    conn=None,
) -> list[dict]:
    """Specifically PROMISES — the "did the party promise that NPC a
    favor" thread that AI DMs forget at session 3 if you don't trip them
    over it."""
    scoped_clause, scoped_params = _principal_scoped_clause(principal_id)
    rows = execute_query(
        f"""
        SELECT id, session_id, summary, entities, patch, evidence, visibility, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND status = 'APPLIED'
          AND visibility = ANY(%s)
          {scoped_clause}
          AND event_type = 'promise_made'
        ORDER BY created_at DESC
        """,
        (str(campaign_id), _visibility_filter(visibility), *scoped_params),
        conn=conn,
    )
    return [attach_sources(dict(r)) for r in rows]


def npc_memory(
    campaign_id: uuid.UUID,
    npc_id: str,
    *,
    visibility: str = "dm",
    principal_id: str | None = None,
    conn=None,
) -> list[dict]:
    """Everything the patch log has recorded about one NPC.
    `npc_id` can be a UUID string or a pre-canonical name — we match
    against the entities array."""
    scoped_clause, scoped_params = _principal_scoped_clause(principal_id)
    rows = execute_query(
        f"""
        SELECT id, session_id, event_type, summary, patch, evidence, visibility,
               confidence, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND status = 'APPLIED'
          AND visibility = ANY(%s)
          {scoped_clause}
          AND entities @> %s::jsonb
        ORDER BY created_at
        """,
        (
            str(campaign_id),
            _visibility_filter(visibility),
            *scoped_params,
            '["%s"]' % npc_id.replace('"', '\\"'),
        ),
        conn=conn,
    )
    return [attach_sources(dict(r)) for r in rows]


def contradictions(campaign_id: uuid.UUID) -> list[dict]:
    """retcon_or_contradiction patches — items the extractor flagged
    but never auto-applied. DM has to resolve."""
    rows = execute_query(
        """
        SELECT id, session_id, summary, entities, evidence, confidence, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND event_type = 'retcon_or_contradiction'
          AND status IN ('PENDING', 'APPROVED', 'EDITED')
        ORDER BY created_at DESC
        """,
        (str(campaign_id),),
    )
    return [attach_sources(dict(r)) for r in rows]
