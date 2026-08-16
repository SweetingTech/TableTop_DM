import uuid

import pytest

pytestmark = pytest.mark.unit


def test_sources_for_recap_includes_visible_rag_and_ledger_sources(monkeypatch):
    from services.session_intel import recap

    patches = [
        {
            "event_type": "unresolved_thread",
            "summary": "The bell still matters.",
            "entities": [],
            "patch": {},
            "evidence": [
                {
                    "source_kind": "ledger_event",
                    "source_id": "42",
                    "quote": "We ring the bell.",
                },
                {
                    "source_kind": "rag_chunk",
                    "source_id": "chunk-1",
                    "doc_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "filename": "bell_lore.md",
                    "visibility": "party",
                    "excerpt": "The bell answers vows.",
                },
            ],
            "visibility": "party",
            "confidence": 0.8,
        }
    ]
    monkeypatch.setattr(
        recap, "_patches_for", lambda session_id, visibility_filter: patches
    )

    sources = recap.sources_for_recap(uuid.uuid4(), "party")

    assert {
        "kind": "ledger_event",
        "id": "42",
        "quote": "We ring the bell.",
        "timestamp_start": None,
        "timestamp_end": None,
    } in sources
    rag = [s for s in sources if s["kind"] == "rag_chunk"][0]
    assert rag["filename"] == "bell_lore.md"
    assert rag["excerpt"] == "The bell answers vows."


def test_sources_for_party_recap_omits_dm_only_rag_sources(monkeypatch):
    from services.session_intel import recap

    patches = [
        {
            "event_type": "unresolved_thread",
            "summary": "The secret bell still matters.",
            "entities": [],
            "patch": {},
            "evidence": [
                {
                    "source_kind": "rag_chunk",
                    "source_id": "chunk-secret",
                    "filename": "bell_dm-only.md",
                    "visibility": "dm_only",
                    "excerpt": "Only the signet silences it.",
                }
            ],
            "visibility": "party",
            "confidence": 0.8,
        }
    ]
    monkeypatch.setattr(
        recap, "_patches_for", lambda session_id, visibility_filter: patches
    )

    assert recap.sources_for_recap(uuid.uuid4(), "party") == []
    assert (
        recap.sources_for_recap(uuid.uuid4(), "dm")[0]["filename"] == "bell_dm-only.md"
    )
