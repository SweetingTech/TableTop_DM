"""Unit-test the embedding profile signature + collection naming.
DB-level behavior (retire-on-switch, NEEDS_REINDEX cascade) is tested
in the integration smoke. Here we just lock the pure logic."""

import pytest

pytestmark = pytest.mark.unit


def test_signature_is_stable_across_calls():
    from services.rag.embedding_profile import signature_for

    s1 = signature_for("openai", "text-embedding-3-small")
    s2 = signature_for("openai", "text-embedding-3-small")
    assert s1 == s2
    assert len(s1) == 8


def test_signature_changes_when_model_changes():
    from services.rag.embedding_profile import signature_for

    s_a = signature_for("openai", "text-embedding-3-small")
    s_b = signature_for("openai", "text-embedding-3-large")
    assert s_a != s_b


def test_signature_changes_when_provider_changes():
    from services.rag.embedding_profile import signature_for

    s_a = signature_for("openai", "text-embedding-3-small")
    s_b = signature_for("ollama", "text-embedding-3-small")
    assert s_a != s_b


def test_signature_case_insensitive():
    from services.rag.embedding_profile import signature_for

    a = signature_for("OpenAI", "Text-Embedding-3-Small")
    b = signature_for("openai", "text-embedding-3-small")
    assert a == b


def test_legacy_collection_name_format():
    from services.rag.embedding_profile import legacy_collection_name

    out = legacy_collection_name("11111111-2222-3333-4444-555555555555")
    # UUID dashes replaced with underscores, suffix _rag, ttdm_ prefix
    assert out == "ttdm_11111111_2222_3333_4444_555555555555_rag"
