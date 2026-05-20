import uuid

import pytest

pytestmark = pytest.mark.unit


def _row(seq_id=1, text="We ring the Black Bell."):
    return {
        "seq_id": seq_id,
        "type": "DIALOGUE",
        "payload": {"speaker_name": "Aria", "dialogue": text},
    }


def _rag_context():
    from services.rag.retriever import RagChunk, RagContext

    chunk = RagChunk(
        doc_id="doc-1",
        chunk_id="chunk-1",
        filename="saint_orun_dm-only.md",
        page=None,
        text="The Black Bell binds the Ashen Choir.",
        score=0.91,
        metadata={"visibility": "dm_only"},
    )
    return RagContext(
        query="Black Bell",
        chunks=[chunk],
        context_block="[1] saint_orun_dm-only.md chunk_id=chunk-1",
        citations=["[1] saint_orun_dm-only.md"],
    )


def test_rag_supported_llm_event_is_dm_reviewed_and_dm_only(monkeypatch):
    from services.session_intel import extractor
    from shared.schemas.session_intel import ExtractionRequest
    import services.llm.adapter as adapter_module

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def generate_structured(self, **kwargs):
            assert "Relevant campaign lore" in kwargs["user_prompt"]
            return {
                "events": [
                    {
                        "event_type": "unresolved_thread",
                        "summary": "The bell may implicate the Ashen Choir.",
                        "entities": ["Black Bell"],
                        "proposed_state_delta": {"summary": "Bell tied to Ashen Choir"},
                        "evidence": [
                            {
                                "source_kind": "ledger_event",
                                "source_id": "1",
                                "quote": "We ring the Black Bell.",
                            },
                            {"source_kind": "rag_chunk", "source_id": "chunk-1"},
                        ],
                        "confidence": 0.86,
                        "visibility": "party",
                        "requires_dm_review": False,
                    }
                ]
            }

    monkeypatch.setattr(
        extractor, "retrieve_session_intel_context", lambda **kwargs: _rag_context()
    )
    monkeypatch.setattr(adapter_module, "LLMAdapter", FakeAdapter)

    req = ExtractionRequest(campaign_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()))
    events, skips = extractor._llm_events(req, [_row()])

    assert skips == []
    assert len(events) == 1
    event = events[0]
    assert event.requires_dm_review is True
    assert event.visibility == "dm_only"
    rag_evidence = [e for e in event.evidence if e.source_kind == "rag_chunk"][0]
    assert rag_evidence.filename == "saint_orun_dm-only.md"
    assert rag_evidence.excerpt == "The Black Bell binds the Ashen Choir."


def test_rag_failure_does_not_block_llm_extraction(monkeypatch):
    from services.session_intel import extractor
    from services.rag.retriever import RagContext
    from shared.schemas.session_intel import ExtractionRequest
    import services.llm.adapter as adapter_module

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def generate_structured(self, **kwargs):
            return {
                "events": [
                    {
                        "event_type": "promise_made",
                        "summary": "Aria promised to bury the bones.",
                        "entities": ["Aria"],
                        "proposed_state_delta": {"summary": "Bury the bones"},
                        "evidence": [
                            {
                                "source_kind": "ledger_event",
                                "source_id": "1",
                                "quote": "I promise.",
                            }
                        ],
                        "confidence": 0.8,
                        "visibility": "party",
                        "requires_dm_review": True,
                    }
                ]
            }

    monkeypatch.setattr(
        extractor,
        "retrieve_session_intel_context",
        lambda **kwargs: RagContext(
            query="",
            chunks=[],
            context_block="",
            citations=[],
            skipped_reason="qdrant_down",
        ),
    )
    monkeypatch.setattr(adapter_module, "LLMAdapter", FakeAdapter)

    req = ExtractionRequest(campaign_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()))
    events, skips = extractor._llm_events(
        req, [_row(text="I promise to bury the bones.")]
    )

    assert skips == []
    assert len(events) == 1
    assert events[0].summary == "Aria promised to bury the bones."


def test_rag_only_source_kind_is_not_used_as_patch_row_source_kind():
    from services.session_intel.extractor import _row_source_kind
    from shared.schemas.session_intel import Evidence

    evidence = [Evidence(source_kind="rag_chunk", source_id="chunk-1")]
    assert _row_source_kind(evidence) == "chat"


def test_llm_extractor_retries_and_recovers_local_model_schema_errors(monkeypatch):
    from services.session_intel import extractor
    from services.rag.retriever import RagContext
    from shared.schemas.session_intel import ExtractionRequest
    import services.llm.adapter as adapter_module

    class FakeAdapter:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def generate_structured(self, **kwargs):
            FakeAdapter.calls += 1
            if FakeAdapter.calls == 1:
                return {
                    "events": [
                        {
                            "event_type": "local_model_made_this_up",
                            "summary": "Bad type",
                            "confidence": 0.8,
                            "visibility": "party",
                        }
                    ]
                }
            assert "failed validation" in kwargs["user_prompt"]
            return {
                "events": [
                    {
                        "event_type": "promise_made",
                        "summary": "Aria promised to bury the bones.",
                        "evidence": [
                            {
                                "source_kind": "ledger_event",
                                "source_id": "1",
                                "quote": "I promise.",
                            }
                        ],
                        "confidence": 0.8,
                        "visibility": "party",
                    }
                ]
            }

    monkeypatch.setattr(
        extractor,
        "retrieve_session_intel_context",
        lambda **kwargs: RagContext(
            query="", chunks=[], context_block="", citations=[]
        ),
    )
    monkeypatch.setattr(adapter_module, "LLMAdapter", FakeAdapter)

    req = ExtractionRequest(campaign_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()))
    events, skips = extractor._llm_events(
        req, [_row(text="I promise to bury the bones.")]
    )

    assert len(events) == 1
    assert events[0].event_type == "promise_made"
    assert any(s.startswith("retry_recovered_after:") for s in skips)


def test_llm_extractor_canonicalizes_safe_event_alias(monkeypatch):
    from services.session_intel import extractor
    from services.rag.retriever import RagContext
    from shared.schemas.session_intel import ExtractionRequest
    import services.llm.adapter as adapter_module

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def generate_structured(self, **kwargs):
            return {
                "events": [
                    {
                        "event_type": "npc_relationship_changed",
                        "summary": "The guard warms to Aria.",
                        "evidence": [
                            {
                                "source_kind": "ledger_event",
                                "source_id": "1",
                                "quote": "You helped us.",
                            }
                        ],
                        "confidence": 0.8,
                        "visibility": "party",
                    }
                ]
            }

    monkeypatch.setattr(
        extractor,
        "retrieve_session_intel_context",
        lambda **kwargs: RagContext(
            query="", chunks=[], context_block="", citations=[]
        ),
    )
    monkeypatch.setattr(adapter_module, "LLMAdapter", FakeAdapter)

    req = ExtractionRequest(campaign_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()))
    events, skips = extractor._llm_events(req, [_row(text="You helped us.")])

    assert skips == []
    assert events[0].event_type == "npc_attitude_changed"
