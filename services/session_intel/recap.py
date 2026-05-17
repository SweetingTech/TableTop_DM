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


log = logging.getLogger(__name__)


def _patches_for(session_id: str, visibility_filter: list[str]) -> list[dict]:
    rows = execute_query(
        """
        SELECT event_type, summary, entities, patch, visibility, confidence
        FROM state.proposed_story_patches
        WHERE session_id = %s
          AND status IN ('APPLIED', 'APPROVED', 'EDITED')
          AND visibility = ANY(%s)
        ORDER BY created_at
        """,
        (session_id, visibility_filter),
    )
    return [dict(r) for r in rows]


def _format_bullets(patches: list[dict]) -> str:
    if not patches:
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
        "dm":        ["public", "party", "dm_only", "principal_scoped"],
        "party":     ["public", "party"],
        "principal": ["public", "party", "principal_scoped"],
        "public":    ["public"],
    }
    filt = visibility_filters.get(visibility, visibility_filters["party"])
    patches = _patches_for(str(session_id), filt)

    bullets = _format_bullets(patches)

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
