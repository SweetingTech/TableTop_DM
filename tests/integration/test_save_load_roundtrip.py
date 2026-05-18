from __future__ import annotations

from io import BytesIO
import uuid

import psycopg2
import pytest

from app import app
from services.saves.crypto import decrypt_save, peek_header

pytestmark = pytest.mark.integration


CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"
PLAYER_ID = "22222222-2222-2222-2222-222222222222"
PC_ID = "33333333-3333-3333-3333-333333333331"
PASSPHRASE = "phase-43-roundtrip"


def _upload(blob: bytes, *, replace: bool = False, passphrase: str = PASSPHRASE):
    return {
        "file": (BytesIO(blob), "roundtrip.ttdm"),
        "passphrase": passphrase,
        "replace": "true" if replace else "false",
    }


def test_game_save_export_import_conflict_replace_and_player_state(integration_stack, postgres_dsn):
    del integration_stack
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger.session_ledger (
                    event_id, event_version, contract_version, type, campaign_id, session_id,
                    sender_principal_id, payload, visible_to, domain_tags, idempotency_key
                ) VALUES (
                    %s, 1, 1, 'NARRATION', %s, %s, %s,
                    '{"message":"Save roundtrip visible event"}'::jsonb,
                    ARRAY[%s]::uuid[], ARRAY['save_roundtrip'], %s
                )
                """,
                (str(uuid.uuid4()), CAMPAIGN_ID, SESSION_ID, PLAYER_ID, PLAYER_ID, "save-roundtrip-event"),
            )
    finally:
        conn.close()

    with app.test_client() as client:
        exported = client.post(
            "/api/saves/game/export",
            json={"campaign_id": CAMPAIGN_ID, "passphrase": PASSPHRASE},
        )
        assert exported.status_code == 200
        blob = exported.data
        assert blob.startswith(b"ttdm-save:v1\n")
        assert peek_header(blob)["kind"] == "game"

        wrong = client.post(
            "/api/saves/game/import",
            data=_upload(blob, passphrase="wrong-passphrase"),
            content_type="multipart/form-data",
        )
        assert wrong.status_code == 400
        assert "Decryption failed" in wrong.get_json()["error"]

        conflict = client.post(
            "/api/saves/game/import",
            data=_upload(blob, replace=False),
            content_type="multipart/form-data",
        )
        assert conflict.status_code == 409
        assert conflict.get_json()["conflict"] is True

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE state.entities SET name = 'Broken Roundtrip Name' WHERE id = %s", (PC_ID,))
    finally:
        conn.close()

    with app.test_client() as client:
        restored = client.post(
            "/api/saves/game/import",
            data=_upload(blob, replace=True),
            content_type="multipart/form-data",
        )
        assert restored.status_code == 200
        assert restored.get_json()["campaign_id"] == CAMPAIGN_ID

        state = client.get(
            f"/api/sessions/{SESSION_ID}/player_state",
            query_string={"principal_id": PLAYER_ID},
        )
        assert state.status_code == 200
        controlled = state.get_json()["player_state"]["controlled_entities"]
        assert any(entity["entity_id"] == PC_ID for entity in controlled)
        assert all(entity["name"] != "Broken Roundtrip Name" for entity in controlled)

    payload = decrypt_save(blob, passphrase=PASSPHRASE, expected_kind="game")
    assert payload["ledger_events"]
    assert all("visible_to" in event for event in payload["ledger_events"])


def test_program_save_exports_clear_keys_and_import_reencrypts(integration_stack, postgres_dsn):
    del integration_stack
    with app.test_client() as client:
        saved = client.put(
            "/api/global_settings/api_keys",
            json={"openrouter": "sk-test-openrouter", "openai": ""},
        )
        assert saved.status_code == 200

        exported = client.post(
            "/api/saves/program/export",
            json={"passphrase": PASSPHRASE},
        )
        assert exported.status_code == 200
        blob = exported.data
        assert blob.startswith(b"ttdm-save:v1\n")
        assert peek_header(blob)["kind"] == "program"

    payload = decrypt_save(blob, passphrase=PASSPHRASE, expected_kind="program")
    api_keys = next(row for row in payload["global_settings"] if row["key"] == "api_keys")
    assert api_keys["value"]["openrouter"] == "sk-test-openrouter"

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM state.global_settings WHERE key = 'api_keys'")
    finally:
        conn.close()

    with app.test_client() as client:
        imported = client.post(
            "/api/saves/program/import",
            data=_upload(blob),
            content_type="multipart/form-data",
        )
        assert imported.status_code == 200
        assert imported.get_json()["settings_imported"] >= 1

    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM state.global_settings WHERE key = 'api_keys'")
            value = cur.fetchone()[0]
    finally:
        conn.close()

    assert value["openrouter"].startswith("vault:v1:")
