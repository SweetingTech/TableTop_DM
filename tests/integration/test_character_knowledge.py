from __future__ import annotations

import os
import secrets
import uuid

import psycopg2
import pytest

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from tests.unit.kernel.test_character_context_api import check_pinned_knowledge

pytestmark = pytest.mark.integration


def test_pinned_knowledge_survives_restart_and_does_not_follow_new_card_text(
    integration_stack, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    scope = admin.post("/api/v2/worlds", json={"name": "Knowledge " + uuid.uuid4().hex}).get_json()
    admin, player, card, endpoint, run = check_pinned_knowledge(app, scope=scope)
    world, branch = card["world_id"], scope["canonical_branch_id"]
    spoken = player.post(
        "/api/v2/commands",
        json={
            "world_id": world,
            "branch_id": branch,
            "run_id": run,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.dialogue.speak",
            "parameters": {"text": "PRIVATE_RECOLLECTION brass gate."},
            "idempotency_key": "remembered-gate",
        },
    )
    assert spoken.status_code == 200, spoken.get_json()
    before = player.get(endpoint, query_string={"query": "PRIVATE_RECOLLECTION"}).get_json()
    assert before["items"]
    restored_app = create_app(artifact_root=tmp_path)
    restored = restored_app.test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert (
        restored.get(endpoint, query_string={"query": "PRIVATE_RECOLLECTION"}).get_json() == before
    )
    assert restored.get(endpoint, query_string={"query": "NEW_SECRET"}).get_json()["items"] == []
    assert restored.get(endpoint, query_string={"query": "ferry"}).get_json()["items"]
    inspector = admin.post(
        "/api/v2/actors",
        json={
            "world_id": world,
            "display_name": "Scene-only inspector",
            "kind": "AGENT",
            "capabilities": ["world.read", "world.read.all"],
        },
    )
    assert inspector.status_code == 201, inspector.get_json()
    headers = {"X-TTDM-Actor-ID": inspector.get_json()["actor_id"]}
    result = admin.get(endpoint, headers=headers, query_string={"query": "PRIVATE_RECOLLECTION"})
    assert result.status_code == 200 and result.get_json()["items"] == []
    situation = admin.get(
        endpoint.removesuffix("knowledge") + "context", headers=headers
    ).get_json()["situation"]
    assert situation["identity"] is None and situation["experiences"] == []


def test_durable_knowledge_waits_for_projector_and_operator_events_never_become_evidence(
    integration_stack, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    scope = admin.post(
        "/api/v2/worlds", json={"name": "Delayed knowledge " + uuid.uuid4().hex}
    ).get_json()
    admin, player, card, endpoint, run = check_pinned_knowledge(app, scope=scope)
    app.extensions["simulation"].configure_subjective_projector(lambda receipt: None)
    base = {"world_id": card["world_id"], "branch_id": scope["canonical_branch_id"], "run_id": run}
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.dialogue.speak",
            "embodied_entity_id": card["entity_id"],
            "parameters": {"text": "The old tower has a copper bell."},
            "idempotency_key": "delayed-bell",
        },
    )
    assert response.status_code == 200, response.get_json()
    pending = player.get(endpoint, query_string={"query": "copper bell"})
    assert pending.status_code == 409, pending.get_json()
    WorldEventProjector(integration_stack.database_url).run_once(limit=1000)
    learned = player.get(endpoint, query_string={"query": "copper bell"})
    assert learned.status_code == 200, learned.get_json()
    assert [row["text"] for row in learned.get_json()["items"]] == [
        "The old tower has a copper bell."
    ]
    with psycopg2.connect(integration_stack.admin_url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM cognition.observations o JOIN sim.events e "
            "ON o.source_event_id=e.event_id WHERE e.world_id=%s "
            "AND e.domain_tags && ARRAY['operator','director','evaluation',"
            "'timeline_revision','checkpoint','protection_policy']",
            (card["world_id"],),
        )
        assert cursor.fetchone()[0] == 0


def test_trial_testimony_never_enters_the_same_body_on_canonical_branch(
    integration_stack, monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", integration_stack.database_url)
    monkeypatch.setenv("TTDM_OPERATOR_TOKEN", secrets.token_urlsafe(32))
    app = create_app(artifact_root=tmp_path)
    admin = app.test_client()
    admin.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    scope = admin.post(
        "/api/v2/worlds", json={"name": "Fork knowledge " + uuid.uuid4().hex}
    ).get_json()
    admin, player, card, endpoint, run = check_pinned_knowledge(app, scope=scope)
    world = card["world_id"]
    snap = admin.post(f"/api/v2/worlds/{world}/snapshots", json={})
    assert snap.status_code == 201, snap.get_json()
    trial = admin.post(
        f"/api/v2/snapshots/{snap.get_json()['snapshot_id']}/branches", json={"seed": 910}
    )
    assert trial.status_code == 201, trial.get_json()
    branch = trial.get_json()
    command = player.post(
        "/api/v2/commands",
        json={
            "world_id": world,
            "branch_id": branch["branch_id"],
            "run_id": branch["run"]["run_id"],
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.dialogue.speak",
            "parameters": {"text": "ABANDONED_TESTIMONY the cedar shrine fell."},
            "idempotency_key": "trial-only-lore",
        },
    )
    assert command.status_code == 200, command.get_json()
    fork_endpoint = endpoint.replace(scope["canonical_branch_id"], branch["branch_id"])
    assert player.get(
        fork_endpoint,
        query_string={"run_id": branch["run"]["run_id"], "query": "ABANDONED_TESTIMONY"},
    ).get_json()["items"]
    assert (
        player.get(endpoint, query_string={"query": "ABANDONED_TESTIMONY"}).get_json()["items"]
        == []
    )
    restored = create_app(artifact_root=tmp_path).test_client()
    restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
    assert (
        restored.get(endpoint, query_string={"query": "ABANDONED_TESTIMONY"}).get_json()["items"]
        == []
    )
