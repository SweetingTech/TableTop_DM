from __future__ import annotations

import secrets
from uuid import UUID

import pytest

from cognition.projector import ClaimedWorldEvent, WorldEventProjector
from kernel.api.app import create_app

pytestmark = pytest.mark.integration


def test_scene_refresh_reads_external_projector_without_replacing_shared_cache(
    integration_stack, monkeypatch, tmp_path
):
    token = secrets.token_urlsafe(24)
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", token)
    app = create_app(artifact_root=tmp_path)
    client = app.test_client()
    headers = {"X-TTDM-Operator-Token": token}
    ids = app.extensions["demo_ids"]
    simulation = app.extensions["simulation"]
    captured = []
    simulation.configure_subjective_projector(captured.append)
    result = client.post(
        "/api/v2/commands",
        headers=headers,
        json={
            "command_type": "tabletop.dialogue.speak",
            "world_id": str(ids["world_id"]),
            "branch_id": str(ids["branch_id"]),
            "run_id": str(ids["run_id"]),
            "embodied_entity_id": str(ids["hero_id"]),
            "parameters": {"text": "The external projector delivered this report."},
            "idempotency_key": "scene-external-" + secrets.token_hex(8),
        },
    )
    assert result.status_code == 200
    cursor = result.get_json()["scene_refresh"]
    path = f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}/entities/{ids['hero_id']}"
    pending = client.get(
        path + "/scene", headers=headers, query_string={"after_event_id": cursor["event_id"]}
    )
    assert pending.status_code == 200
    assert pending.get_json()["refresh"]["ready"] is False
    receipt = captured[0]
    projector = WorldEventProjector(integration_stack.database_url)
    item = ClaimedWorldEvent(0, receipt.event, receipt.perceptions)
    projector._project(item)
    projector._project(item)  # Durable retry must not duplicate the observation.
    ready = client.get(
        path + "/scene", headers=headers, query_string={"after_event_id": cursor["event_id"]}
    )
    assert ready.status_code == 200
    payload = ready.get_json()
    assert payload["refresh"] == {"event_id": cursor["event_id"], "ready": True, "observed": True}
    rows = [
        row
        for row in payload["recent_observations"]
        if row["source_event_id"] == cursor["event_id"]
    ]
    assert len(rows) == 1
    # Only the reader's local snapshot was hydrated; the unrelated in-process projector
    # cache must not be overwritten as a side effect of an RLS-scoped GET.
    assert not app.extensions["minds"].has_observation(
        UUID(rows[0]["observation_id"]), branch_id=ids["branch_id"]
    )
    context = client.get(path + "/context", headers=headers)
    assert context.status_code == 200
    assert len(context.get_json()["action_candidates"]) == 4
    assert context.get_json()["action_catalog_version"] == "tabletop-character-actions-1.1.0"
    assert "external projector delivered" in str(context.get_json()["situation"]["experiences"])
    assert simulation.states.get(ids["branch_id"]).version == cursor["projection_version"]

    restarted = create_app(artifact_root=tmp_path)
    restored = restarted.test_client().get(
        path + "/scene", headers=headers, query_string={"after_event_id": cursor["event_id"]}
    )
    assert restored.status_code == 200
    assert restored.get_json()["refresh"]["ready"] is True
    restored_context = restarted.test_client().get(path + "/context", headers=headers)
    assert restored_context.status_code == 200
    assert (
        restored_context.get_json()["action_candidates"] == context.get_json()["action_candidates"]
    )
    assert [
        row
        for row in restored.get_json()["recent_observations"]
        if row["source_event_id"] == cursor["event_id"]
    ] == rows
