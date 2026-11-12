from __future__ import annotations

import pytest

from kernel.api.app import create_app

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "route,payload",
    [
        ("/api/v2/personas", {"seed": 31, "dimensions": {}}),
        ("/api/v2/personas/generate", {"seed": 31, "fixed": {}}),
    ],
)
def test_persona_purpose_round_trips_and_filters_prompts(monkeypatch, tmp_path, route, payload):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    client = create_app(artifact_root=tmp_path).test_client()
    rejected = client.post(route, json={**payload, "purpose": "UNKNOWN"})
    assert rejected.status_code == 400
    assert client.get("/api/v2/personas").get_json() == []
    response = client.post(route, json={**payload, "purpose": "CHARACTER"})
    assert response.status_code == 201
    document = response.get_json()
    blueprint = document.get("blueprint", document)
    assert blueprint["purpose"] == "CHARACTER"
    identity = blueprint["persona_id"]
    assert client.get(f"/api/v2/personas/{identity}").get_json()["purpose"] == "CHARACTER"
    compiled = client.post(f"/api/v2/personas/{identity}/compile").get_json()
    assert compiled["purpose"] == "CHARACTER"
    assert "dm_trust" not in compiled["deep_traits"]
    prompt = client.post(
        f"/api/v2/personas/{identity}/prompt",
        json={
            "relevant_traits": ["dm_trust", "reading_tolerance", "risk_tolerance"],
        },
    ).get_json()
    assert prompt["included_traits"] == ["risk_tolerance"]
    default = client.post(route, json=payload).get_json()
    assert default.get("blueprint", default)["purpose"] == "SIMULATED_PLAYTESTER"


@pytest.mark.parametrize("reference", ["persona_id", "parent_version_id"])
def test_character_successor_inherits_purpose_and_rejects_reclassification(
    monkeypatch, tmp_path, reference
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    client = create_app(artifact_root=tmp_path).test_client()
    created = client.post("/api/v2/personas", json={"seed": 32, "purpose": "CHARACTER"}).get_json()
    identity = created["blueprint"]["persona_id"]
    value = identity if reference == "persona_id" else created["version"]["version_id"]
    update = {"seed": 33, reference: value}
    successor = client.post("/api/v2/personas", json=update)
    assert successor.status_code == 201
    assert successor.get_json()["blueprint"]["purpose"] == "CHARACTER"
    assert successor.get_json()["blueprint"]["persona_id"] == identity
    versions_before = client.get(f"/api/v2/personas/{identity}/versions").get_json()
    rejected = client.post("/api/v2/personas", json={**update, "purpose": "SIMULATED_PLAYTESTER"})
    assert rejected.status_code == 400
    assert client.get(f"/api/v2/personas/{identity}/versions").get_json() == versions_before
    compiled = client.post(f"/api/v2/personas/{identity}/compile").get_json()
    assert compiled["purpose"] == "CHARACTER"
    assert compiled["starting_goals"] == []
    assert compiled["starting_relationships"] == []
