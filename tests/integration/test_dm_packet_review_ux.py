from __future__ import annotations

import json
import uuid

import psycopg2
import pytest

from app import app

pytestmark = pytest.mark.integration

CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"


def _insert_patch(postgres_dsn: str, *, event_type: str = "location_changed") -> str:
    patch_id = str(uuid.uuid4())
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO state.proposed_story_patches (
                    id, campaign_id, session_id, source_kind, source_ref,
                    event_type, summary, entities, patch, evidence,
                    confidence, visibility, status
                )
                VALUES (
                    %s, %s, %s, 'ledger_event', '{"seq_ids":[42]}'::jsonb,
                    %s, 'QA patch summary', '[]'::jsonb,
                    %s::jsonb,
                    '[{"source_kind":"ledger_event","source_id":"42","quote":"QA evidence"}]'::jsonb,
                    1.0, 'party', 'PENDING'
                )
                """,
                (
                    patch_id,
                    CAMPAIGN_ID,
                    SESSION_ID,
                    event_type,
                    json.dumps({"current_location": "QA Review Chamber"}),
                ),
            )
    finally:
        conn.close()
    return patch_id


def test_batch_patch_approve_applies_and_updates_story_state(
    integration_stack, postgres_dsn
):
    del integration_stack
    patch_id = _insert_patch(postgres_dsn)

    with app.test_client() as client:
        response = client.post(
            "/api/patches/batch",
            json={"action": "approve", "patch_ids": [patch_id]},
        )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM state.proposed_story_patches WHERE id = %s",
                (patch_id,),
            )
            assert cur.fetchone()[0] == "APPLIED"
            cur.execute(
                "SELECT current_location FROM state.story_state WHERE session_id = %s",
                (SESSION_ID,),
            )
            assert cur.fetchone()[0] == "QA Review Chamber"
    finally:
        conn.close()


def test_patch_supersede_creates_pending_replacement(integration_stack, postgres_dsn):
    del integration_stack
    patch_id = _insert_patch(postgres_dsn)

    with app.test_client() as client:
        response = client.post(
            f"/api/patches/{patch_id}/supersede",
            json={
                "summary": "Replacement QA summary",
                "patch": {"current_location": "Replacement Chamber"},
                "visibility": "dm_only",
            },
        )

    assert response.status_code == 200
    replacement = response.get_json()
    assert replacement["summary"] == "Replacement QA summary"
    assert replacement["status"] == "PENDING"
    assert replacement["visibility"] == "dm_only"
    assert replacement["source_ref"]["supersedes_patch_id"] == patch_id

    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM state.proposed_story_patches WHERE id = %s",
                (patch_id,),
            )
            assert cur.fetchone()[0] == "SUPERSEDED"
    finally:
        conn.close()
