import pytest

from services.llm.adapter import LLMAdapter

pytestmark = pytest.mark.unit


def test_mock_mode_returns_deterministic_structured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    adapter = LLMAdapter()
    result = adapter.generate_structured(
        "system",
        "user",
        response_schema={
            "type": "object",
            "properties": {"narration": {"type": "string"}},
            "required": ["narration"],
        },
    )
    assert "narration" in result


def test_mock_mode_returns_deterministic_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    adapter = LLMAdapter()
    assert adapter.generate_text("system", "user").startswith("[MockLLM]")
