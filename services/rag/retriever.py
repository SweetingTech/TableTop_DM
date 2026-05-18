"""Centralized RAG retrieval (Phase 39 step 1).

Replaces the ad-hoc qdrant queries that were smeared across app.py.
Callers ask for "context for purpose X relevant to query Y" and receive
a normalized RagContext object with chunk text, citations, and a
ready-to-inject prompt block.

The retriever owns:
  - Query embedding (delegated to LLMAdapter)
  - Qdrant search against the campaign's ACTIVE embedding profile
    collection (falls back to the legacy collection name for backwards
    compatibility with pre-Phase-39 uploads)
  - Server-side payload filters (campaign_id, visibility, entity tags)
  - Visibility re-check after fetch (defensive — chunks without a
    visibility tag default to 'public')

Callers must NOT instantiate Qdrant clients directly. If you find
yourself wanting to, put it here instead.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Literal
from urllib import request as urllib_request, error as urllib_error

from shared.db.connection import execute_one

from .embedding_profile import (
    collection_for_campaign,
    legacy_collection_name,
)
from .filters import (
    ACCESS_MATRIX,
    build_qdrant_filter,
    filter_chunk_visibility,
)


log = logging.getLogger(__name__)


Purpose = Literal["dm_narration", "npc_dialogue", "session_intel",
                  "recap_dm", "recap_party", "recap_public"]


@dataclass
class RagChunk:
    doc_id: str
    chunk_id: str
    filename: str
    page: Optional[int]
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class RagContext:
    query: str
    chunks: list[RagChunk]
    context_block: str
    citations: list[str]
    skipped_reason: Optional[str] = None


# ----- Qdrant HTTP plumbing -----
# Kept private to this module so app.py can eventually drop its copies.

def _qdrant_base_url() -> str:
    host = os.environ.get("QDRANT_HOST", "localhost")
    port = int(os.environ.get("QDRANT_HTTP_PORT", "6333"))
    return f"http://{host}:{port}"


def _qdrant_request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{_qdrant_base_url()}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib_request.Request(url, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise RuntimeError(f"Qdrant HTTP {e.code}: {body[:200]}")
    except Exception as e:
        raise RuntimeError(f"Qdrant request failed: {e}")


def _collection_exists(name: str) -> bool:
    try:
        _qdrant_request("GET", f"/collections/{name}")
        return True
    except Exception:
        return False


def _resolve_collection(campaign_id: str) -> Optional[str]:
    """Return the right Qdrant collection to read from for this campaign,
    or None if there's nothing indexed yet. Prefers the active embedding
    profile; falls back to the legacy collection name if no profile
    exists but the legacy collection does."""
    active = collection_for_campaign(campaign_id)
    if active and _collection_exists(active):
        return active
    legacy = legacy_collection_name(campaign_id)
    if _collection_exists(legacy):
        return legacy
    return active  # may be None; caller handles


# ----- Public API -----

def retrieve_campaign_context(
    campaign_id: str,
    query: str,
    *,
    session_id: Optional[str] = None,
    entity_ids: Optional[list[str]] = None,
    top_k: int = 5,
    purpose: Purpose = "dm_narration",
    principal_id: Optional[str] = None,
    npc_known_tags: Optional[set] = None,
) -> RagContext:
    """Retrieve up to ``top_k`` chunks relevant to ``query`` from the
    campaign's RAG store, filtered for the given purpose.

    Never raises — failures (no collection, no embedder, Qdrant down)
    become an empty context with ``skipped_reason`` set. The caller's
    LLM prompt is built so missing context is graceful.
    """
    if not query or not campaign_id:
        return RagContext(query=query or "", chunks=[], context_block="",
                          citations=[], skipped_reason="empty_query_or_campaign")

    # 1. Embed the query.
    try:
        from services.llm.adapter import LLMAdapter
        import uuid as _uuid
        adapter = LLMAdapter(campaign_id=_uuid.UUID(campaign_id), role="dm")
        embed = adapter.embed_texts([query])
        vectors = embed.get("vectors") or []
        if not vectors:
            return RagContext(query=query, chunks=[], context_block="",
                              citations=[], skipped_reason="empty_embedding")
        query_vector = vectors[0]
    except Exception as e:
        log.info("RAG: embedding failed (%s); returning empty context", e)
        return RagContext(query=query, chunks=[], context_block="",
                          citations=[], skipped_reason=f"embed_failed: {e}")

    # 2. Resolve collection.
    collection = _resolve_collection(campaign_id)
    if not collection:
        return RagContext(query=query, chunks=[], context_block="",
                          citations=[], skipped_reason="no_collection")

    # 3. Server-side filter.
    allowed_vis = list(ACCESS_MATRIX.get(purpose, {"public"}))
    qfilter = build_qdrant_filter(
        campaign_id=campaign_id,
        visibility_in=allowed_vis,
        entity_ids=entity_ids,
        session_ids=[session_id] if session_id else None,
    )

    # 4. Search.
    body = {
        "vector": query_vector,
        "limit": max(1, min(top_k * 4, 50)),  # over-fetch for client-side filtering
        "with_payload": True,
    }
    if qfilter:
        body["filter"] = qfilter
    try:
        response = _qdrant_request(
            "POST", f"/collections/{collection}/points/search", body
        )
    except RuntimeError as e:
        log.info("RAG: qdrant search failed (%s); returning empty", e)
        return RagContext(query=query, chunks=[], context_block="",
                          citations=[], skipped_reason=str(e))

    # 5. Normalize + re-check visibility client-side.
    raw = response.get("result") or []
    chunks_raw = []
    for r in raw:
        payload = r.get("payload") or {}
        chunks_raw.append({
            "doc_id": payload.get("doc_id", ""),
            "chunk_id": payload.get("chunk_id", ""),
            "filename": payload.get("source_filename") or payload.get("filename", ""),
            "page": payload.get("page"),
            "text": payload.get("text", ""),
            "score": float(r.get("score") or 0.0),
            "metadata": payload,
        })
    filtered = filter_chunk_visibility(
        chunks_raw, purpose,
        principal_id=principal_id, npc_known_tags=npc_known_tags,
    )

    # 6. Re-rank deterministically (vector score with a small recency bias),
    # then trim to top_k.
    def _final_score(c):
        score = c["score"]
        return score
    filtered.sort(key=_final_score, reverse=True)
    final = filtered[:top_k]

    chunks = [RagChunk(**c) for c in final]
    block, cits = _build_context_block(chunks, purpose)
    return RagContext(query=query, chunks=chunks, context_block=block,
                      citations=cits)


def _build_context_block(chunks: list[RagChunk], purpose: str) -> tuple[str, list[str]]:
    """Format chunks into a prompt-injectable block. Kept close to the
    retriever so consumers don't reimplement it."""
    if not chunks:
        return "", []
    label = {
        "dm_narration":  "CAMPAIGN LORE CONTEXT (use when relevant; do not invent beyond these facts)",
        "npc_dialogue":  "NPC KNOWLEDGE CONTEXT (only what this NPC could plausibly know)",
        "session_intel": "LORE CONTEXT (cite these in evidence when an inference rests on them)",
        "recap_dm":      "LORE TIE-INS (DM-visible; cite source filenames)",
        "recap_party":   "LORE TIE-INS (party-safe)",
        "recap_public":  "PUBLIC LORE TIE-INS",
    }.get(purpose, "LORE CONTEXT")

    lines = [label]
    citations = []
    for i, c in enumerate(chunks, 1):
        cite = f"[{i}] {c.filename}" + (f" p.{c.page}" if c.page else "")
        citations.append(cite)
        text = c.text.strip().replace("\n", " ")
        if len(text) > 800:
            text = text[:800] + "…"
        chunk_ref = f" chunk_id={c.chunk_id}" if c.chunk_id else ""
        lines.append(f"{cite}{chunk_ref}: {text}")
    return "\n".join(lines), citations
