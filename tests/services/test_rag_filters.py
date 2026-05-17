"""Visibility filter tests — the critical leak-prevention boundary.

dm_only lore must never reach NPC dialogue or party recaps regardless of
how relevant cosine similarity thinks it is. These tests assert that
filter_chunk_visibility enforces the access matrix correctly.
"""

import pytest

pytestmark = pytest.mark.unit


def _chunk(visibility=None, tags=None, allowed_principals=None, text="some lore"):
    return {
        "doc_id": "d1",
        "chunk_id": "c1",
        "filename": "lore.md",
        "page": None,
        "text": text,
        "score": 0.9,
        "metadata": {
            **({"visibility": visibility} if visibility else {}),
            **({"tags": tags} if tags else {}),
            **({"allowed_principals": allowed_principals} if allowed_principals else {}),
        },
    }


def test_dm_only_chunk_never_reaches_party_recap():
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(visibility="dm_only", text="villain's true name")]
    assert filter_chunk_visibility(chunks, "recap_party") == []


def test_dm_only_chunk_never_reaches_npc_dialogue():
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(visibility="dm_only", text="cursed bell silences the choir")]
    assert filter_chunk_visibility(chunks, "npc_dialogue") == []


def test_dm_only_chunk_DOES_reach_dm_narration():
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(visibility="dm_only", text="secret known to the DM only")]
    out = filter_chunk_visibility(chunks, "dm_narration")
    assert len(out) == 1


def test_public_chunk_reaches_everywhere():
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(visibility="public", text="common knowledge")]
    for purpose in ("dm_narration", "npc_dialogue", "recap_party",
                    "recap_dm", "recap_public", "session_intel"):
        assert len(filter_chunk_visibility(chunks, purpose)) == 1, f"failed for {purpose}"


def test_party_chunk_omitted_from_public_recap():
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(visibility="party", text="party-only intel")]
    assert filter_chunk_visibility(chunks, "recap_public") == []
    assert len(filter_chunk_visibility(chunks, "recap_party")) == 1


def test_principal_scoped_requires_matching_principal():
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(visibility="principal_scoped",
                     allowed_principals=["pid-a"],
                     text="secret known only to Aria")]
    # Wrong principal
    assert filter_chunk_visibility(chunks, "recap_dm", principal_id="pid-b") == []
    # Correct principal
    out = filter_chunk_visibility(chunks, "recap_dm", principal_id="pid-a")
    assert len(out) == 1


def test_npc_dialogue_respects_known_lore_tags():
    from services.rag.filters import filter_chunk_visibility
    # NPC knows about chapel + cult tags only
    npc_tags = {"chapel", "cult"}
    chunks = [
        _chunk(visibility="party", tags=["chapel"], text="The chapel was sealed by the Order."),
        _chunk(visibility="party", tags=["unrelated-faction"], text="The Guild charges tolls in the south."),
    ]
    out = filter_chunk_visibility(chunks, "npc_dialogue", npc_known_tags=npc_tags)
    texts = [c["text"] for c in out]
    assert "The chapel was sealed by the Order." in texts
    assert "The Guild charges tolls in the south." not in texts


def test_chunk_without_visibility_metadata_defaults_to_public():
    """Legacy chunks predate the visibility tag — they should keep
    flowing to dm/party but never get treated as dm_only by accident."""
    from services.rag.filters import filter_chunk_visibility
    chunks = [_chunk(text="legacy chunk", visibility=None)]
    # default 'public' → allowed everywhere
    assert len(filter_chunk_visibility(chunks, "npc_dialogue")) == 1
    assert len(filter_chunk_visibility(chunks, "recap_party")) == 1


def test_build_qdrant_filter_minimal():
    from services.rag.filters import build_qdrant_filter
    f = build_qdrant_filter(campaign_id="c1")
    assert f == {"must": [{"key": "campaign_id", "match": {"value": "c1"}}]}


def test_build_qdrant_filter_with_visibility_and_entities():
    from services.rag.filters import build_qdrant_filter
    f = build_qdrant_filter(
        campaign_id="c1",
        visibility_in=["public", "party"],
        entity_ids=["e1", "e2"],
    )
    keys = [m["key"] for m in f["must"]]
    assert "campaign_id" in keys
    assert "visibility" in keys
    assert "entity_ids" in keys


def test_build_qdrant_filter_empty_when_no_constraints():
    from services.rag.filters import build_qdrant_filter
    f = build_qdrant_filter()
    assert f == {}
