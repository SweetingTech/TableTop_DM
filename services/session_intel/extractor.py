"""Session-intelligence extractor (Phase 33).

Reads chat / ledger / dm_notes within a session window and produces
ExtractedStoryEvent proposals. Each proposal becomes a row in
state.proposed_story_patches with status='PENDING' for the DM to review.

Two extraction paths, both feeding the same queue:

  1. Deterministic — derived directly from a STATE_DELTA / TOOL_CALL
     ledger row. Confidence 1.0. No LLM needed. Fires for things like
     "PC moved", "HP changed", "encounter ended".
  2. LLM-driven — DIALOGUE rows + DM notes are summarised by the
     LLMAdapter into structured ExtractedStoryEvent[]. Confidence
     comes from the model. The output is schema-validated; anything
     that doesn't fit the contract is dropped with a skip reason.

The deterministic path runs first so cheap, certain facts beat
expensive inferences into the queue. The LLM path is then asked to fill
in the *interpretive* layer ("the guard turned pale = NPC attitude
change") on top of those raw deltas.
"""

import json
import logging
import uuid
from typing import Any, get_args

from pydantic import ValidationError

from shared.db.connection import execute_query, get_connection
from shared.schemas.session_intel import (
    ExtractedStoryEvent,
    Evidence,
    ExtractionRequest,
    ExtractionResult,
    SourceKind,
    StoryEventType,
    Visibility,
)
from services.session_intel.rag_context import (
    hydrate_rag_evidence,
    retrieve_session_intel_context,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Deterministic path: ledger rows → ExtractedStoryEvent
# ---------------------------------------------------------------------


def _deterministic_events(rows: list[dict]) -> list[ExtractedStoryEvent]:
    """Convert raw ledger rows into ExtractedStoryEvent for things we
    KNOW happened (because the deterministic engine committed them).
    Confidence is 1.0 because the ledger is canonical truth."""
    out: list[ExtractedStoryEvent] = []
    for r in rows:
        kind = r.get("type")
        payload = r.get("payload") or {}
        seq_id = str(r.get("seq_id"))

        # Movement → location_changed candidate (heuristic: only if it's
        # the first move into a "named" location; raw tile movement is too
        # granular). We keep it simple here — emit a location_changed event
        # only when the tool_call carries a location_name field.
        if kind == "TOOL_CALL" and (
            payload.get("tool_name") in ("move_entity", "transition_map")
        ):
            loc = payload.get("location_name") or payload.get("destination_name")
            if loc:
                out.append(
                    ExtractedStoryEvent(
                        event_type="location_changed",
                        summary=f"Party entered {loc}",
                        entities=[],
                        proposed_state_delta={"current_location": loc},
                        evidence=[
                            Evidence(
                                source_kind="ledger_event", source_id=seq_id, quote=None
                            )
                        ],
                        confidence=1.0,
                        visibility="party",
                        requires_dm_review=False,
                    )
                )

        # Combat death → consequence_created
        if kind == "STATE_DELTA":
            deltas = payload.get("deltas") or []
            for d in deltas:
                if d.get("table") == "state.entities" and isinstance(
                    d.get("changes"), dict
                ):
                    changes = d["changes"]
                    if changes.get("hp_current") == 0 and changes.get("status") in (
                        "DEAD",
                        "DOWN",
                    ):
                        out.append(
                            ExtractedStoryEvent(
                                event_type="consequence_created",
                                summary=f"Entity {d.get('entity_id', '?')[:8]} dropped (hp=0)",
                                entities=[d.get("entity_id")]
                                if d.get("entity_id")
                                else [],
                                proposed_state_delta={
                                    "kind": "death",
                                    "entity_id": d.get("entity_id"),
                                },
                                evidence=[
                                    Evidence(
                                        source_kind="ledger_event",
                                        source_id=seq_id,
                                        quote=None,
                                    )
                                ],
                                confidence=1.0,
                                visibility="party",
                                requires_dm_review=True,
                            )
                        )
    return out


# ---------------------------------------------------------------------
# LLM-driven path: DIALOGUE + DM notes → ExtractedStoryEvent
# ---------------------------------------------------------------------

_EXTRACTOR_SYSTEM = """\
You are the session-intelligence layer of a tabletop RPG engine. The
deterministic backend already commits mechanical state changes (hp,
position, encounter rounds). Your job is to spot *narrative facts*
implied by chat and DM notes that the engine wouldn't catch on its own:

- a PC made a promise to an NPC
- an NPC's attitude toward the party shifted
- a secret was revealed (to whom?)
- a new quest hook surfaced
- a thread was left dangling
- a consequence was set up for later

You MUST return JSON matching the response_schema. Do not invent
mechanical state. If you aren't sure, lower your confidence; if you have
no evidence text, omit the event entirely. Cite the verbatim quote that
supports each event in the `evidence[].quote` field.
"""


_EXTRACTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": list(get_args(StoryEventType)),
                    },
                    "summary": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "proposed_state_delta": {"type": "object"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_kind": {
                                    "type": "string",
                                    "enum": list(get_args(SourceKind)),
                                },
                                "source_id": {"type": "string"},
                                "quote": {"type": "string"},
                                "doc_id": {"type": "string"},
                                "chunk_id": {"type": "string"},
                                "filename": {"type": "string"},
                                "page": {"type": ["integer", "null"]},
                                "visibility": {
                                    "type": "string",
                                    "enum": list(get_args(Visibility)),
                                },
                                "excerpt": {"type": "string"},
                                "score": {"type": "number"},
                            },
                            "required": ["source_kind", "source_id"],
                        },
                    },
                    "confidence": {"type": "number"},
                    "visibility": {
                        "type": "string",
                        "enum": list(get_args(Visibility)),
                    },
                    "requires_dm_review": {"type": "boolean"},
                },
                "required": ["event_type", "summary", "confidence", "visibility"],
            },
        }
    },
    "required": ["events"],
}


_EVENT_TYPE_ALIASES = {
    "npc_relationship_changed": "npc_attitude_changed",
    "npc_relation_changed": "npc_attitude_changed",
    "relationship_changed": "npc_attitude_changed",
}


def _canonicalize_event_payload(event: dict) -> dict:
    cloned = dict(event)
    event_type = cloned.get("event_type")
    if isinstance(event_type, str):
        cloned["event_type"] = _EVENT_TYPE_ALIASES.get(event_type, event_type)
    return cloned


def _format_chat_window(rows: list[dict]) -> str:
    """Render ledger rows in a way the LLM can reason about."""
    lines = []
    for r in rows:
        kind = r.get("type")
        if kind == "DIALOGUE":
            p = r.get("payload") or {}
            speaker = p.get("speaker_name") or p.get("speaker_entity_id", "?")
            text = p.get("dialogue") or p.get("message") or ""
            lines.append(f"[seq {r['seq_id']}] {speaker}: {text}")
        elif kind == "NARRATION":
            p = r.get("payload") or {}
            text = p.get("narration") or ""
            lines.append(f"[seq {r['seq_id']}] DM (narrating): {text}")
        elif kind == "TOOL_CALL":
            p = r.get("payload") or {}
            lines.append(f"[seq {r['seq_id']}] (mechanic: {p.get('tool_name', '?')})")
    return "\n".join(lines)


def _llm_events(
    req: ExtractionRequest, rows: list[dict]
) -> tuple[list[ExtractedStoryEvent], list[str]]:
    """Ask the LLM for narrative-inference events. Returns (events, skips).
    Empty list if no LLM is configured or the call fails."""
    try:
        from services.llm.adapter import LLMAdapter
    except Exception as e:
        return [], [f"llm_adapter_unavailable: {e}"]

    transcript = _format_chat_window(rows)
    if not transcript.strip():
        return [], ["empty_transcript"]

    rag = retrieve_session_intel_context(
        campaign_id=req.campaign_id,
        session_id=req.session_id,
        rows=rows,
    )

    user_prompt = (
        "Below is the recent session transcript and mechanical events. "
        "Extract narrative facts you would write into a DM tracking sheet. "
        "Cite quotes.\n\n"
        f"{transcript}\n"
    )
    if rag.context_block:
        user_prompt += (
            "\n\nRelevant campaign lore follows. Use it only to support proposals; "
            "never treat lore as an already-committed play fact. If a proposed "
            "event depends on lore, include a rag_chunk evidence item using the "
            "chunk id shown in the citation, set requires_dm_review=true, and "
            "keep dm_only lore out of party/public visibility.\n\n"
            f"{rag.context_block}\n"
        )

    def parse_events(raw: dict) -> tuple[list[ExtractedStoryEvent], list[str]]:
        events_raw = raw.get("events") or []
        parsed: list[ExtractedStoryEvent] = []
        local_skips: list[str] = []
        for i, ev in enumerate(events_raw):
            try:
                ev = _canonicalize_event_payload(ev)
                evidence = ev.get("evidence") or []
                if isinstance(evidence, list):
                    ev["evidence"] = hydrate_rag_evidence(evidence, rag)
                event = ExtractedStoryEvent(**ev)
                _enforce_rag_review_rules(event)
                parsed.append(event)
            except ValidationError as e:
                local_skips.append(f"event_{i}_validation: {str(e)[:200]}")
        return parsed, local_skips

    try:
        adapter = LLMAdapter(campaign_id=uuid.UUID(req.campaign_id), role="dm")
        raw = adapter.generate_structured(
            system_prompt=_EXTRACTOR_SYSTEM,
            user_prompt=user_prompt,
            response_schema=_EXTRACTOR_SCHEMA,
        )
    except Exception as e:
        return [], [f"llm_call_failed: {e}"]

    out, skips = parse_events(raw)
    if skips:
        try:
            retry_prompt = (
                f"{user_prompt}\n\nYour previous response failed validation:\n"
                + "\n".join(skips)
                + "\nReturn only valid JSON matching the schema. Use only these event_type values: "
                + ", ".join(get_args(StoryEventType))
                + "."
            )
            retry_raw = adapter.generate_structured(
                system_prompt=_EXTRACTOR_SYSTEM,
                user_prompt=retry_prompt,
                response_schema=_EXTRACTOR_SCHEMA,
            )
            retry_out, retry_skips = parse_events(retry_raw)
            if retry_out:
                out = retry_out
                skips = [f"retry_recovered_after: {s}" for s in skips] + retry_skips
            else:
                skips.extend(f"retry_{s}" for s in retry_skips)
        except Exception as e:
            skips.append(f"llm_retry_failed: {e}")
    return out, skips


def _enforce_rag_review_rules(event: ExtractedStoryEvent) -> None:
    """RAG-supported inference always requires DM review.

    DM-only lore also forces the proposed fact to DM-only visibility, so
    a model cannot accidentally leak a secret implication into a party
    recap or patch.
    """
    rag_items = [e for e in event.evidence if e.source_kind == "rag_chunk"]
    if not rag_items:
        return
    event.requires_dm_review = True
    if any((e.visibility or "").lower() == "dm_only" for e in rag_items):
        event.visibility = "dm_only"


def _row_source_kind(evidence: list[Evidence]) -> str:
    """Pick a DB-level source_kind allowed by migration 013.

    RAG chunks are evidence/provenance, but the proposal row still comes
    from chat/transcript/ledger/dm_note. Avoid violating the existing
    CHECK constraint.
    """
    for item in evidence:
        if item.source_kind != "rag_chunk":
            return item.source_kind
    return "chat"


# ---------------------------------------------------------------------
# Public API: extract + persist to proposed_story_patches
# ---------------------------------------------------------------------


def extract_and_queue(req: ExtractionRequest) -> ExtractionResult:
    """Run the extractor over a session window and write proposals to
    state.proposed_story_patches. Returns ids of the rows inserted."""

    # 1. Pull the ledger window.
    where = ["session_id = %s"]
    params: list[Any] = [req.session_id]
    if req.since_seq_id is not None:
        where.append("seq_id > %s")
        params.append(req.since_seq_id)
    if req.until_seq_id is not None:
        where.append("seq_id <= %s")
        params.append(req.until_seq_id)
    rows = execute_query(
        f"SELECT seq_id, type, payload FROM ledger.session_ledger "
        f"WHERE {' AND '.join(where)} ORDER BY seq_id",
        tuple(params),
    )
    rows = [dict(r) for r in rows]

    events = _deterministic_events(rows)
    skips: list[str] = []
    if not req.deterministic_only:
        llm_events, llm_skips = _llm_events(req, rows)
        events.extend(llm_events)
        skips.extend(llm_skips)

    # 2. Persist as PENDING rows.
    inserted: list[str] = []
    if events:
        conn = get_connection()
        try:
            cur = conn.cursor()
            for ev in events:
                cur.execute(
                    """
                    INSERT INTO state.proposed_story_patches
                      (campaign_id, session_id, source_kind, source_ref,
                       event_type, summary, entities, patch, evidence,
                       confidence, visibility)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                    RETURNING id
                    """,
                    (
                        req.campaign_id,
                        req.session_id,
                        _row_source_kind(ev.evidence),
                        json.dumps({"seq_ids": [e.source_id for e in ev.evidence]}),
                        ev.event_type,
                        ev.summary,
                        json.dumps(ev.entities),
                        json.dumps(ev.proposed_state_delta),
                        json.dumps([e.dict() for e in ev.evidence]),
                        round(float(ev.confidence), 3),
                        ev.visibility,
                    ),
                )
                inserted.append(str(cur.fetchone()[0]))
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return ExtractionResult(
        proposed_count=len(inserted),
        patch_ids=inserted,
        skipped=skips,
    )
