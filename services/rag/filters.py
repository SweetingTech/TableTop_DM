"""Filter rules for RAG retrieval.

Two layers:

  - Qdrant payload filter (server-side): cheap and exact. Limits the
    candidate set before scoring. Applied by retriever.py.
  - Visibility filter (post-fetch): visibility metadata might not yet
    be on every legacy chunk, so we re-check it after retrieval and
    drop disallowed items.

The visibility model mirrors the one Session Intel uses:

    public          — anyone, any recap, any prompt
    party           — players + DM
    dm_only         — DM, AI-DM, NPC dialogue only when the NPC
                      principal has been granted access. Never in
                      party/public recap.
    principal_scoped — only one specific principal can see it
                       (key items, secret quest hooks, etc.)
"""

from typing import Iterable


VISIBILITY_SCOPES = ("public", "party", "dm_only", "principal_scoped")


# Which RAG-chunk visibility levels are allowed for a given consumer.
ACCESS_MATRIX = {
    "dm_narration": {"public", "party", "dm_only"},
    "npc_dialogue": {"public", "party"},  # tightened per-NPC below
    "session_intel": {"public", "party", "dm_only"},
    "recap_dm": {"public", "party", "dm_only", "principal_scoped"},
    "recap_party": {"public", "party"},
    "recap_public": {"public"},
}


def filter_chunk_visibility(
    chunks: Iterable[dict],
    purpose: str,
    *,
    principal_id: str = None,
    npc_known_tags: set = None,
) -> list[dict]:
    """Drop any chunk whose visibility metadata isn't allowed for
    ``purpose``. Chunks without a `visibility` field in metadata
    default to 'public' (so legacy data stays usable, but new uploads
    SHOULD tag visibility explicitly).
    """
    allowed = ACCESS_MATRIX.get(purpose, {"public"})
    out = []
    for c in chunks:
        meta = c.get("metadata") or {}
        vis = (meta.get("visibility") or "public").lower()
        if vis not in VISIBILITY_SCOPES:
            vis = "public"
        if vis not in allowed:
            continue

        # principal_scoped: only the specific principal can see it.
        if vis == "principal_scoped":
            allowed_principals = meta.get("allowed_principals") or []
            if principal_id is None or principal_id not in allowed_principals:
                continue

        # NPC dialogue further filtered by what tags the NPC "knows" —
        # even party-visible lore can be hidden from an NPC that hasn't
        # encountered it yet.
        if purpose == "npc_dialogue" and npc_known_tags is not None:
            tags = set((meta.get("tags") or []))
            if tags and not (tags & npc_known_tags):
                continue

        out.append(c)
    return out


def build_qdrant_filter(
    *,
    campaign_id: str = None,
    visibility_in: Iterable[str] = None,
    entity_ids: Iterable[str] = None,
    location_ids: Iterable[str] = None,
    session_ids: Iterable[str] = None,
    enabled_only: bool = True,
) -> dict:
    """Build a Qdrant payload filter dict. None-valued kwargs are skipped.

    Returns the JSON object Qdrant's search API expects under ``filter``.
    Empty if no constraints supplied — callers should use ``or None``."""
    must = []
    if campaign_id:
        must.append({"key": "campaign_id", "match": {"value": campaign_id}})
    if visibility_in is not None:
        vis = list(visibility_in)
        if vis:
            must.append({"key": "visibility", "match": {"any": vis}})
    if entity_ids:
        must.append({"key": "entity_ids", "match": {"any": list(entity_ids)}})
    if location_ids:
        must.append({"key": "location_ids", "match": {"any": list(location_ids)}})
    if session_ids:
        must.append({"key": "session_ids", "match": {"any": list(session_ids)}})
    if enabled_only:
        # Documents can be toggled enabled=false in the UI; payloads
        # carry this flag at ingest time. Treat missing as enabled
        # (legacy) by not requiring the field — covered by upsert path.
        pass
    return {"must": must} if must else {}
