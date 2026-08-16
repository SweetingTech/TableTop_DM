"""Compose RAG-aware prompt context for the DM/NPC/Intel agents.

The retriever produces a ``RagContext.context_block`` already, but
``context_builder`` is the seam where we combine it with story_state,
recent ledger excerpts, and entity facts. Agents call this instead of
hand-stitching strings.

This module is intentionally thin — it just glues facts together. No
LLM calls, no DB writes. The point is to make the *shape* of agent
input uniform so we can change retrieval logic without touching every
agent.
"""

from typing import Optional

from shared.db.connection import execute_one

from .retriever import RagContext, retrieve_campaign_context


def _story_state_block(session_id: Optional[str]) -> str:
    if not session_id:
        return ""
    row = execute_one(
        "SELECT current_location, game_time, active_npcs, active_quests, "
        "plot_threads, party_resources FROM state.story_state "
        "WHERE session_id = %s",
        (session_id,),
    )
    if not row:
        return ""
    parts = ["CURRENT STORY STATE"]
    if row.get("current_location"):
        parts.append(f"  Location: {row['current_location']}")
    if row.get("game_time"):
        parts.append(f"  Time: {row['game_time']}")
    active_npcs = row.get("active_npcs") or []
    if active_npcs:
        names = [n.get("summary") or n.get("name") or "?" for n in active_npcs[:5]]
        parts.append(f"  NPCs present: {', '.join(names)}")
    quests = row.get("active_quests") or []
    if quests:
        titles = [q.get("summary") or q.get("title") or "?" for q in quests[:3]]
        parts.append(f"  Active quests: {', '.join(titles)}")
    threads = row.get("plot_threads") or []
    if threads:
        items = [t.get("summary") or "?" for t in threads[:3]]
        parts.append(f"  Open threads: {', '.join(items)}")
    return "\n".join(parts)


def build_dm_narration_context(
    *,
    campaign_id: str,
    session_id: Optional[str],
    user_context: str,
    query_hint: Optional[str] = None,
    top_k: int = 4,
) -> tuple[str, RagContext]:
    """Assemble the prompt prefix the DMNarrationAgent feeds to the LLM.

    Returns (prefix_text, RagContext) so callers can also surface
    citations in their response payload.
    """
    # Use the explicit user context as the retrieval query unless caller
    # gives a tighter hint. story_state location keeps the retrieval
    # focused on the current scene's lore.
    location = ""
    if session_id:
        row = execute_one(
            "SELECT current_location FROM state.story_state WHERE session_id = %s",
            (session_id,),
        )
        if row and row.get("current_location"):
            location = row["current_location"]
    retrieval_query = (
        query_hint or " ".join(filter(None, [location, user_context]))[:400]
    )

    rag = retrieve_campaign_context(
        campaign_id=campaign_id,
        query=retrieval_query,
        session_id=session_id,
        top_k=top_k,
        purpose="dm_narration",
    )

    pieces = []
    if rag.context_block:
        pieces.append(rag.context_block)
    state_block = _story_state_block(session_id)
    if state_block:
        pieces.append(state_block)
    return "\n\n".join(pieces), rag


def build_npc_dialogue_context(
    *,
    campaign_id: str,
    session_id: Optional[str],
    npc_entity_id: Optional[str],
    player_utterance: str,
    top_k: int = 3,
) -> tuple[str, RagContext]:
    """Assemble the prompt prefix for NPC dialogue. Tightened visibility:
    public + party only by default. NPC-specific known-tags would
    further restrict (TODO when entity-level lore-tag metadata exists)."""
    npc_known_tags = None
    if npc_entity_id:
        row = execute_one(
            "SELECT public_sheet, secret_sheet, tags FROM state.entities WHERE id = %s",
            (npc_entity_id,),
        )
        if row:
            # An NPC's tags + sheet hints describe what knowledge they
            # plausibly have. Empty means we fall back to public+party
            # (cautious default).
            tagset = set(row.get("tags") or [])
            sheet_tags = (row.get("public_sheet") or {}).get("known_lore_tags")
            if isinstance(sheet_tags, list):
                tagset.update(sheet_tags)
            npc_known_tags = tagset or None

    location = ""
    if session_id:
        row = execute_one(
            "SELECT current_location FROM state.story_state WHERE session_id = %s",
            (session_id,),
        )
        if row and row.get("current_location"):
            location = row["current_location"]
    retrieval_query = " ".join(filter(None, [location, player_utterance]))[:400]

    rag = retrieve_campaign_context(
        campaign_id=campaign_id,
        query=retrieval_query,
        session_id=session_id,
        top_k=top_k,
        purpose="npc_dialogue",
        npc_known_tags=npc_known_tags,
    )

    pieces = []
    if rag.context_block:
        pieces.append(rag.context_block)
    state_block = _story_state_block(session_id)
    if state_block:
        pieces.append(state_block)
    return "\n\n".join(pieces), rag
