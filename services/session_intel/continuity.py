"""Continuity queries (Phase 38).

Surface the "what should resurface next session" view of the patch log.
All read-only — these endpoints don't write anything; they're filtered
projections of state.proposed_story_patches and state.story_state.

Each query is intentionally simple. The data model is already where the
intelligence lives — these are just convenience SQL.
"""

import uuid

from shared.db.connection import execute_query


def open_threads(campaign_id: uuid.UUID) -> list[dict]:
    """Plot threads that haven't been resolved yet. A thread is 'open'
    if it has an APPLIED unresolved_thread/promise/threat/consequence
    patch and no later APPLIED patch references it as resolved."""
    rows = execute_query(
        """
        SELECT id, session_id, event_type, summary, entities, patch,
               visibility, confidence, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND status = 'APPLIED'
          AND event_type IN ('unresolved_thread', 'promise_made',
                             'threat_created', 'consequence_created')
        ORDER BY created_at DESC
        """,
        (str(campaign_id),),
    )
    return [dict(r) for r in rows]


def unresolved_promises(campaign_id: uuid.UUID) -> list[dict]:
    """Specifically PROMISES — the "did the party promise that NPC a
    favor" thread that AI DMs forget at session 3 if you don't trip them
    over it."""
    rows = execute_query(
        """
        SELECT id, session_id, summary, entities, patch, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND status = 'APPLIED'
          AND event_type = 'promise_made'
        ORDER BY created_at DESC
        """,
        (str(campaign_id),),
    )
    return [dict(r) for r in rows]


def npc_memory(campaign_id: uuid.UUID, npc_id: str) -> list[dict]:
    """Everything the patch log has recorded about one NPC.
    `npc_id` can be a UUID string or a pre-canonical name — we match
    against the entities array."""
    rows = execute_query(
        """
        SELECT id, session_id, event_type, summary, patch, visibility,
               confidence, created_at
        FROM state.proposed_story_patches
        WHERE campaign_id = %s
          AND status = 'APPLIED'
          AND entities @> %s::jsonb
        ORDER BY created_at
        """,
        (str(campaign_id), '["%s"]' % npc_id.replace('"', '\\"')),
    )
    return [dict(r) for r in rows]


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
    return [dict(r) for r in rows]
