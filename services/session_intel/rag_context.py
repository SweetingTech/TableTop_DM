"""RAG context helpers for Session Intel.

RAG is provenance for proposals, not authority. This module retrieves
campaign lore for the extractor and turns RAG-backed evidence into
serializable source objects for DM packets, recaps, and continuity views.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from services.rag.retriever import RagChunk, RagContext, retrieve_campaign_context


log = logging.getLogger(__name__)


def build_extraction_query(rows: list[dict], *, max_chars: int = 900) -> str:
    """Build a compact retrieval query from player-facing ledger text."""
    lines: list[str] = []
    for row in rows:
        payload = row.get("payload") or {}
        kind = row.get("type")
        if kind == "DIALOGUE":
            speaker = payload.get("speaker_name") or payload.get("speaker_entity_id") or "?"
            text = payload.get("dialogue") or payload.get("message") or ""
            if text:
                lines.append(f"{speaker}: {text}")
        elif kind == "NARRATION":
            text = payload.get("narration") or ""
            if text:
                lines.append(f"DM: {text}")
        elif kind == "TOOL_CALL":
            tool = payload.get("tool_name")
            location = payload.get("location_name") or payload.get("destination_name")
            if tool or location:
                lines.append(" ".join(filter(None, [str(tool or ""), str(location or "")])))
    return "\n".join(lines)[-max_chars:]


def retrieve_session_intel_context(
    *,
    campaign_id: str,
    session_id: str,
    rows: list[dict],
    top_k: int = 4,
) -> RagContext:
    """Retrieve lore for extraction. Fail open: empty context on errors."""
    query = build_extraction_query(rows)
    if not query.strip():
        return RagContext(query="", chunks=[], context_block="", citations=[],
                          skipped_reason="empty_extraction_query")
    try:
        return retrieve_campaign_context(
            campaign_id=campaign_id,
            session_id=session_id,
            query=query,
            purpose="session_intel",
            top_k=top_k,
        )
    except Exception as exc:
        log.info("session-intel RAG retrieval skipped: %s", exc)
        return RagContext(query=query, chunks=[], context_block="", citations=[],
                          skipped_reason=f"rag_failed: {exc}")


def chunk_evidence(chunk: RagChunk) -> dict[str, Any]:
    """Convert a retrieved chunk into the evidence JSON shape."""
    excerpt = (chunk.text or "").strip().replace("\n", " ")
    if len(excerpt) > 500:
        excerpt = excerpt[:500] + "..."
    visibility = (chunk.metadata or {}).get("visibility") or "public"
    return {
        "source_kind": "rag_chunk",
        "source_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "chunk_id": chunk.chunk_id,
        "filename": chunk.filename,
        "page": chunk.page,
        "visibility": visibility,
        "excerpt": excerpt,
        "score": chunk.score,
    }


def hydrate_rag_evidence(evidence: list[dict[str, Any]], rag: Optional[RagContext]) -> list[dict[str, Any]]:
    """Fill model-returned rag_chunk evidence with retriever metadata."""
    if not rag or not rag.chunks:
        return evidence
    by_id = {c.chunk_id: c for c in rag.chunks}
    hydrated: list[dict[str, Any]] = []
    for item in evidence:
        if item.get("source_kind") != "rag_chunk":
            hydrated.append(item)
            continue
        key = item.get("chunk_id") or item.get("source_id")
        chunk = by_id.get(str(key)) if key is not None else None
        if not chunk:
            hydrated.append(item)
            continue
        merged = {**chunk_evidence(chunk), **{k: v for k, v in item.items() if v is not None}}
        if not merged.get("source_id"):
            merged["source_id"] = chunk.chunk_id
        hydrated.append(merged)
    return hydrated


def evidence_sources(evidence: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return UI/API source objects from patch evidence, de-duplicated."""
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence or []:
        kind = item.get("source_kind") or item.get("kind")
        source_id = str(item.get("source_id") or item.get("id") or item.get("chunk_id") or "")
        if not kind or not source_id:
            continue
        key = (str(kind), source_id)
        if key in seen:
            continue
        seen.add(key)
        if kind == "rag_chunk":
            sources.append({
                "kind": "rag_chunk",
                "id": source_id,
                "doc_id": item.get("doc_id"),
                "chunk_id": item.get("chunk_id") or source_id,
                "filename": item.get("filename"),
                "page": item.get("page"),
                "visibility": item.get("visibility"),
                "excerpt": item.get("excerpt") or item.get("quote"),
                "score": item.get("score"),
            })
        else:
            sources.append({
                "kind": kind,
                "id": source_id,
                "quote": item.get("quote"),
                "timestamp_start": item.get("timestamp_start"),
                "timestamp_end": item.get("timestamp_end"),
            })
    return sources


def attach_sources(row: dict[str, Any]) -> dict[str, Any]:
    """Copy a DB row and attach ``sources`` derived from its evidence."""
    out = dict(row)
    evidence = out.get("evidence") or []
    out["sources"] = evidence_sources(evidence if isinstance(evidence, list) else [])
    return out
