"""Embedding-profile management (Phase 39 step 6).

Each (provider, embedding_model) combination is a profile. Each profile
gets its own Qdrant collection so switching models on a live campaign
doesn't silently break old vectors via a dimension mismatch.

Resolution rule for "where do today's vectors live":

  1. Look up the campaign's ACTIVE profile matching its current
     campaign_settings (provider + embedding_model). Create one if it
     doesn't exist.
  2. Return its qdrant_collection name. Caller upserts to that.

Reindex semantics: when the active profile shifts (because the campaign
settings changed), all documents previously embedded under the OLD
profile are marked status='NEEDS_REINDEX'. The old collection is
retained until the DM explicitly cleans it up — that way, retrievals can
still serve from the old vectors during a manual transition window if we
want, and we never lose searchable text data (it's in Postgres
state.rag_chunks regardless).
"""

import hashlib
from typing import Optional

from shared.db.connection import execute_one, execute_query


def signature_for(provider: str, embedding_model: str) -> str:
    """8-char stable hash of (provider|model). Short enough for a
    collection name suffix; collisions across legitimate model names
    are astronomically unlikely."""
    raw = f"{(provider or '').lower()}|{(embedding_model or '').lower()}".encode(
        "utf-8"
    )
    return hashlib.sha1(raw).hexdigest()[:8]


def _collection_name(campaign_id: str, signature: str) -> str:
    return f"ttdm_{campaign_id}_{signature}_rag".replace("-", "_")


def resolve_active_profile(
    campaign_id: str,
    provider: str,
    embedding_model: str,
    *,
    create_if_missing: bool = True,
) -> dict | None:
    """Return the active profile row for this campaign's current
    (provider, model). Creates one if missing and `create_if_missing`.
    Side effect: retires any other ACTIVE profiles for this campaign
    and marks their documents NEEDS_REINDEX."""
    sig = signature_for(provider, embedding_model)
    row = execute_one(
        "SELECT * FROM state.rag_embedding_profiles "
        "WHERE campaign_id = %s AND signature = %s",
        (campaign_id, sig),
    )
    if row and row["active"]:
        return dict(row)

    if not create_if_missing and not row:
        return None

    # Retire whatever was active before — if a different profile is in use,
    # its documents need reindexing.
    prev = execute_one(
        "SELECT id FROM state.rag_embedding_profiles "
        "WHERE campaign_id = %s AND active = true AND signature != %s",
        (campaign_id, sig),
    )
    if prev:
        execute_one(
            "UPDATE state.rag_embedding_profiles SET active = false, retired_at = now() "
            "WHERE id = %s RETURNING id",
            (prev["id"],),
        )
        # All docs that were using the retired profile must be reindexed.
        execute_query(
            "UPDATE state.rag_documents SET status = 'NEEDS_REINDEX', needs_reindex = true, "
            "updated_at = now() WHERE embedding_profile_id = %s",
            (prev["id"],),
            fetch=False,
        )

    if row:
        # Profile exists but was retired earlier — reactivate.
        new_row = execute_one(
            "UPDATE state.rag_embedding_profiles SET active = true, retired_at = NULL "
            "WHERE id = %s RETURNING *",
            (row["id"],),
        )
        return dict(new_row)

    new_row = execute_one(
        "INSERT INTO state.rag_embedding_profiles "
        "  (campaign_id, provider, embedding_model, signature, qdrant_collection) "
        "VALUES (%s, %s, %s, %s, %s) "
        "RETURNING *",
        (
            campaign_id,
            provider,
            embedding_model,
            sig,
            _collection_name(campaign_id, sig),
        ),
    )
    return dict(new_row)


def set_vector_dim(profile_id: str, dim: int) -> None:
    """Set the profile's vector_dim on first successful embedding.
    Idempotent — never overwrites a non-NULL value."""
    execute_one(
        "UPDATE state.rag_embedding_profiles SET vector_dim = COALESCE(vector_dim, %s) "
        "WHERE id = %s RETURNING id",
        (dim, profile_id),
    )


def collection_for_campaign(campaign_id: str) -> Optional[str]:
    """Return the active collection name for a campaign, or None if no
    profile exists yet. Used by retrievers that want to read without
    constructing a profile."""
    row = execute_one(
        "SELECT qdrant_collection FROM state.rag_embedding_profiles "
        "WHERE campaign_id = %s AND active = true",
        (campaign_id,),
    )
    return row["qdrant_collection"] if row else None


def legacy_collection_name(campaign_id: str) -> str:
    """Pre-profile collection name (Phase 39 introduces profiles; rows
    in state.rag_documents from before then point at this name)."""
    return f"ttdm_{campaign_id}_rag".replace("-", "_")
