from services.llm.adapter import select_embedding_model


def test_openai_uses_openai_embedding_default():
    assert select_embedding_model("openai") == "text-embedding-3-small"


def test_ollama_uses_local_embedding_default_and_rejects_openai_fallback():
    assert select_embedding_model("ollama") == "nomic-embed-text"
    assert (
        select_embedding_model("ollama", "text-embedding-3-small") == "nomic-embed-text"
    )


def test_lmstudio_auto_selects_embedding_like_model():
    assert (
        select_embedding_model(
            "lmstudio",
            available_models=["gemma-4-e4b", "text-embedding-nomic-v1"],
        )
        == "text-embedding-nomic-v1"
    )


def test_lmstudio_without_embedding_model_requires_configuration():
    assert select_embedding_model("lmstudio", available_models=["gemma-4-e4b"]) is None
    assert select_embedding_model("lmstudio", "text-embedding-3-small") is None
