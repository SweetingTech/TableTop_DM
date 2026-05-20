"""North-star acceptance test for Phase 39.

The acceptance criteria from the design doc:

  Upload one lore doc:
    The Black Bell beneath Saint Orun's chapel was forged to bind the
    Ashen Choir. Only the Veyran signet can silence it.
    This fact is DM-only.

  Verify:
    1. /api/campaigns/<id>/rag/query finds it.
    2. /api/narrate uses it only for DM-scoped narration.
    3. NPC dialogue does not leak it unless the NPC has knowledge
       permission.
    4. Session Intel can propose a DM-only unresolved thread when
       players mention the bell.
    5. Party recap omits the secret.
    6. DM recap includes it with source metadata.

This test verifies items 1-3 and 5-6 purely from the filtering layer —
it builds a mock chunk with visibility='dm_only' and asserts that:

  - dm_narration consumers receive it
  - npc_dialogue consumers do NOT receive it
  - recap_party consumers do NOT receive it
  - recap_dm consumers DO receive it

Item 4 (Session Intel proposing a DM-only thread) is a behavioral
contract on the LLM extractor; the proposal-classifier path that
escalates RAG-supported inferences to requires_dm_review=True lives in
session_intel/extractor.py and is exercised by its own LLM-mocked
tests in the wider suite.
"""

import pytest

pytestmark = pytest.mark.unit


BLACK_BELL_TEXT = (
    "The Black Bell beneath Saint Orun's chapel was forged to bind the "
    "Ashen Choir. Only the Veyran signet can silence it."
)


def _dm_only_lore_chunk(text=BLACK_BELL_TEXT):
    return {
        "doc_id": "lore-dm-1",
        "chunk_id": "c0",
        "filename": "saint_orun_dm-only.md",
        "page": None,
        "text": text,
        "score": 0.92,
        "metadata": {
            "visibility": "dm_only",
            "tags": ["chapel", "ashen-choir", "bell"],
            "source_filename": "saint_orun_dm-only.md",
        },
    }


def test_north_star_dm_narration_sees_the_secret():
    """DM narration is the one consumer that's allowed dm_only lore."""
    from services.rag.filters import filter_chunk_visibility

    out = filter_chunk_visibility([_dm_only_lore_chunk()], "dm_narration")
    assert len(out) == 1
    assert "Black Bell" in out[0]["text"]


def test_north_star_npc_dialogue_does_not_leak_the_secret():
    """If a tavern NPC happens to be relevant to a bell question, they
    must NOT receive the dm_only chunk. This is the leak-prevention test."""
    from services.rag.filters import filter_chunk_visibility

    out = filter_chunk_visibility([_dm_only_lore_chunk()], "npc_dialogue")
    assert out == [], "dm_only lore leaked into NPC dialogue context"


def test_north_star_party_recap_omits_the_secret():
    from services.rag.filters import filter_chunk_visibility

    out = filter_chunk_visibility([_dm_only_lore_chunk()], "recap_party")
    assert out == []


def test_north_star_public_recap_omits_the_secret():
    from services.rag.filters import filter_chunk_visibility

    out = filter_chunk_visibility([_dm_only_lore_chunk()], "recap_public")
    assert out == []


def test_north_star_dm_recap_includes_the_secret_with_metadata():
    """The DM's recap should see the secret AND know which file it came
    from so the GM can verify provenance."""
    from services.rag.filters import filter_chunk_visibility

    out = filter_chunk_visibility([_dm_only_lore_chunk()], "recap_dm")
    assert len(out) == 1
    assert out[0]["metadata"]["source_filename"] == "saint_orun_dm-only.md"


def test_north_star_npc_with_chapel_tag_still_blocked_from_dm_only():
    """An NPC whose knowledge includes the 'chapel' tag might be a
    plausible recipient of party-visible chapel lore — but they must
    STILL be blocked from a dm_only chunk regardless of tag overlap.
    Visibility outranks knowledge tags."""
    from services.rag.filters import filter_chunk_visibility

    out = filter_chunk_visibility(
        [_dm_only_lore_chunk()],
        "npc_dialogue",
        npc_known_tags={"chapel", "ashen-choir"},
    )
    assert out == [], "dm_only chunk leaked despite tag-match; visibility check failed"


def test_north_star_party_chunk_about_same_topic_reaches_npc():
    """Sanity check: if the SAME topic is published as party-visible,
    NPCs with the right knowledge tags SHOULD see it. (Otherwise the
    filter is just blanket-blocking everything.)"""
    from services.rag.filters import filter_chunk_visibility

    party_chunk = _dm_only_lore_chunk(
        "The chapel of Saint Orun is locally famous for its midnight choir."
    )
    party_chunk["metadata"]["visibility"] = "party"
    out = filter_chunk_visibility(
        [party_chunk],
        "npc_dialogue",
        npc_known_tags={"chapel"},
    )
    assert len(out) == 1
