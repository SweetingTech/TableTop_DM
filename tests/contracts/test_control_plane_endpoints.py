import pytest
from types import SimpleNamespace

from app import app, _openai_client_for

pytestmark = pytest.mark.contracts


def test_campaign_crud_contract(monkeypatch):
    monkeypatch.setattr(
        "shared.db.connection.execute_one",
        lambda *_args, **_kwargs: {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "New Campaign",
            "slug": "new-campaign",
            "status": "ACTIVE",
            "mode": "EXPLORATION",
        },
    )
    with app.test_client() as client:
        r = client.post(
            "/api/campaigns",
            json={"name": "New Campaign", "slug": "new-campaign", "status": "ACTIVE", "mode": "EXPLORATION"},
        )
    assert r.status_code == 201
    assert r.get_json()["slug"] == "new-campaign"


def test_entity_control_validation():
    with app.test_client() as client:
        r = client.post("/api/entities/11111111-1111-1111-1111-111111111111/control", json={"controlled_by": "BOT"})
    assert r.status_code == 400


def test_ai_test_provider_mock():
    with app.test_client() as client:
        r = client.post("/api/ai/test_provider", json={"provider": "mock", "model": "mock-model"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_ai_test_provider_lmstudio_allows_empty_env_api_key(monkeypatch):
    captured = {}

    class _FakeModels:
        @staticmethod
        def list():
            return SimpleNamespace(data=[SimpleNamespace(id="local-model")])

    class _FakeCompletions:
        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeOpenAI:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.models = _FakeModels()
            self.chat = _FakeChat()

    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    with app.test_client() as client:
        r = client.post(
            "/api/ai/test_provider",
            json={
                "provider": "lmstudio",
                "base_url": "http://localhost:1234/v1",
                "model": "local-model",
            },
        )
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert captured["api_key"] == "lmstudio-local"


@pytest.mark.parametrize("provider", ["openai", "ollama", "openrouter"])
def test_openai_client_for_non_lmstudio_keeps_existing_env_behavior(
    monkeypatch, provider
):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url

    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    _openai_client_for(provider, None)

    assert captured["api_key"] == ""
