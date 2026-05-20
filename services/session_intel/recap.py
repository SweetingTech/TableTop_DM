"""Recap generator (Phase 37).

Visibility-aware recaps from the approved/applied patches of a session.
Three flavors:

- 'dm'        — everything: public, party, dm_only, principal_scoped.
                Includes contradictions and unresolved threads.
- 'party'     — public + party. What the players collectively know.
- 'principal' — public + party + only the principal_scoped items the
                given principal can see (TODO: per-PC perception filter).

The recap is one LLM call summarizing the filtered patches into prose.
Falls back to a deterministic bulleted list if no LLM is configured.
"""

import logging
import uuid
from typing import Optional

from shared.db.connection import execute_query
from services.session_intel.rag_context import evidence_sources


log = logging.getLogger(__name__)


def _patches_for(session_id: str, visibility_filter: list[str]) -> list[dict]:
    rows = execute_query(
        """
        SELECT event_type, summary, entities, patch, evidence, visibility, confidence
        FROM state.proposed_story_patches
        WHERE session_id = %s
          AND status IN ('APPLIED', 'APPROVED', 'EDITED')
          AND visibility = ANY(%s)
        ORDER BY created_at
        """,
        (session_id, visibility_filter),
    )
    return [dict(r) for r in rows]


def sources_for_recap(
    session_id: uuid.UUID,
    visibility: str = "party",
    principal_id: Optional[uuid.UUID] = None,
) -> list[dict]:
    """Return source objects for the patches visible in this recap."""
    visibility_filters = {
        "dm": ["public", "party", "dm_only", "principal_scoped"],
        "party": ["public", "party"],
        "principal": ["public", "party", "principal_scoped"],
        "public": ["public"],
    }
    filt = visibility_filters.get(visibility, visibility_filters["party"])
    patches = _patches_for(str(session_id), filt)
    sources: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for patch in patches:
        for source in evidence_sources(patch.get("evidence") or []):
            key = (str(source.get("kind")), str(source.get("id")))
            if key in seen:
                continue
            seen.add(key)
            # Principal-specific filtering is TODO in existing recap
            # behavior; keep this hook so the API shape is ready.
            if visibility != "dm" and source.get("visibility") == "dm_only":
                continue
            sources.append(source)
    return sources


def _ledger_events_for_recap(session_id: str, visibility: str) -> list[dict]:
    where = "session_id = %s"
    params: list[object] = [session_id]
    if visibility != "dm":
        where += " AND COALESCE(payload->>'visibility', '') NOT IN ('dm_only', 'dm')"
    rows = execute_query(
        f"""
        SELECT event_id, type, payload, created_at
        FROM ledger.session_ledger
        WHERE {where}
        ORDER BY seq_id DESC
        LIMIT 20
        """,
        tuple(params),
    )
    return [dict(r) for r in reversed(rows)]


def _format_ledger_event(event: dict) -> str:
    payload = event.get("payload") or {}
    event_type = (
        str(event.get("type") or payload.get("type") or "event")
        .replace("_", " ")
        .title()
    )
    if payload.get("message"):
        return f"{event_type}: {payload['message']}"
    if payload.get("narration"):
        return f"{event_type}: {payload['narration']}"
    if payload.get("summary"):
        return f"{event_type}: {payload['summary']}"
    if payload.get("tool_name"):
        return f"{event_type}: {str(payload['tool_name']).replace('_', ' ')} resolved."
    if payload.get("action_type"):
        return f"{event_type}: {str(payload['action_type']).replace('_', ' ').lower()}."
    return f"{event_type}: game state changed."


def _format_bullets(
    patches: list[dict], ledger_events: list[dict] | None = None
) -> str:
    ledger_events = ledger_events or []
    if not patches and not ledger_events:
        return "Nothing significant recorded this session."
    by_kind: dict[str, list[str]] = {}
    for p in patches:
        by_kind.setdefault(p["event_type"], []).append(p["summary"])
    parts = []
    for kind, items in by_kind.items():
        label = kind.replace("_", " ").title()
        parts.append(f"**{label}**")
        for item in items:
            parts.append(f"  - {item}")
    if ledger_events:
        parts.append("**Session Events**")
        for event in ledger_events:
            parts.append(f"  - {_format_ledger_event(event)}")
    return "\n".join(parts)


_RECAP_SYSTEM = """\
You are summarising one TTRPG session for the GM. Use ONLY the bullet
list provided. Do not invent characters or events. One short paragraph.
Past tense. No second person; refer to "the party" or specific NPC names.
"""


def generate_recap(
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    visibility: str = "party",
    principal_id: Optional[uuid.UUID] = None,
) -> str:
    """Return a recap string for the given visibility scope."""
    visibility_filters = {
        "dm": ["public", "party", "dm_only", "principal_scoped"],
        "party": ["public", "party"],
        "principal": ["public", "party", "principal_scoped"],
        "public": ["public"],
    }
    filt = visibility_filters.get(visibility, visibility_filters["party"])
    patches = _patches_for(str(session_id), filt)
    ledger_events = _ledger_events_for_recap(str(session_id), visibility)

    bullets = _format_bullets(patches, ledger_events)

    # Try LLM polish; fall back to bullets if anything fails.
    try:
        from services.llm.adapter import LLMAdapter

        adapter = LLMAdapter(campaign_id=campaign_id, role="dm")
        prose = adapter.generate_structured(
            system_prompt=_RECAP_SYSTEM,
            user_prompt=f"Session events:\n{bullets}\n\nWrite a recap paragraph.",
            response_schema={
                "type": "object",
                "properties": {"recap": {"type": "string"}},
                "required": ["recap"],
            },
        )
        text = (prose or {}).get("recap") or ""
        if text.strip():
            return text.strip()
    except Exception as e:
        log.info("recap LLM call skipped: %s", e)
    return bullets
