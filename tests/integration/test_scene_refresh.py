from __future__ import annotations

import secrets
from uuid import UUID

import pytest

from cognition.projector import WorldEventProjector
from domains.tabletop.character_actions import ACTION_CATALOG_VERSION
from kernel.api.app import create_app
from tests.integration.test_controller_runner import setup

pytestmark = pytest.mark.integration


def test_scene_refresh_reads_external_projector_without_replacing_shared_cache(
    integration_stack, monkeypatch, tmp_path
):
    app, (_, client, card, _, path, run_id, _) = setup(integration_stack, monkeypatch, tmp_path)
    world_id, branch_id, entity_id = card["world_id"], path.split("/")[6], card["entity_id"]
    topic = f"world.{world_id}.branch.{branch_id}"
    simulation = app.extensions["simulation"]
    captured = []
    simulation.configure_subjective_projector(captured.append)
    result = client.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.dialogue.speak",
            "world_id": world_id,
            "branch_id": branch_id,
            "run_id": run_id,
            "embodied_entity_id": entity_id,
            "parameters": {"text": "The external projector delivered this report."},
            "idempotency_key": "scene-external-" + secrets.token_hex(8),
        },
    )
    assert result.status_code == 200
    cursor = result.get_json()["scene_refresh"]
    pending = client.get(path + "/scene", query_string={"after_event_id": cursor["event_id"]})
    assert pending.status_code == 200
    assert pending.get_json()["refresh"]["ready"] is False
    receipt = captured[0]
    projector = WorldEventProjector(integration_stack.database_url)
    (item,) = projector._claim(1, topic=topic)
    assert item.event.event_id == receipt.event.event_id
    projector._process_claim(item)
    projector._process_claim(item)  # Durable retry must not duplicate the observation.
    ready = client.get(path + "/scene", query_string={"after_event_id": cursor["event_id"]})
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
        UUID(rows[0]["observation_id"]), branch_id=UUID(branch_id)
    )
    context = client.get(path + "/context")
    assert context.status_code == 200
    assert len(context.get_json()["action_candidates"]) == 4
    assert context.get_json()["action_catalog_version"] == ACTION_CATALOG_VERSION
    assert "external projector delivered" in str(context.get_json()["situation"]["experiences"])
    assert simulation.states.get(UUID(branch_id)).version == cursor["projection_version"]

    restarted = create_app(artifact_root=tmp_path)
    restored_client = restarted.test_client()
    restored_client.set_cookie("ttdm_session", client.get_cookie("ttdm_session").value)
    restored = restored_client.get(
        path + "/scene", query_string={"after_event_id": cursor["event_id"]}
    )
    assert restored.status_code == 200
    assert restored.get_json()["refresh"]["ready"] is True
    restored_context = restored_client.get(path + "/context")
    assert restored_context.status_code == 200
    assert (
        restored_context.get_json()["action_candidates"] == context.get_json()["action_candidates"]
    )
    assert [
        row
        for row in restored.get_json()["recent_observations"]
        if row["source_event_id"] == cursor["event_id"]
    ] == rows
