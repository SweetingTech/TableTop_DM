import pytest

pytestmark = pytest.mark.unit


def test_local_openai_compatible_providers_get_dummy_api_key(monkeypatch):
    from services.llm import adapter

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_INTEGRATIONS_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)

    monkeypatch.setattr(adapter, "execute_one", lambda *args, **kwargs: None, raising=False)

    assert adapter._resolve_api_key("lmstudio", {}) == "local-provider"
    assert adapter._resolve_api_key("ollama", {}) == "local-provider"
