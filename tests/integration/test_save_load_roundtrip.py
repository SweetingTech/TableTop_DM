from __future__ import annotations

from io import BytesIO
import uuid

import psycopg2
import pytest

from app import app
from services.saves.crypto import decrypt_save, encrypt_save, peek_header

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


def _rewrite_header(blob: bytes, **updates) -> bytes:
    import json

    magic, header_line, token = blob.split(b"\n", 2)
    header = json.loads(header_line.decode("utf-8"))
    header.update(updates)
    return magic + b"\n" + json.dumps(header).encode("utf-8") + b"\n" + token


def _rewrite_principal_id(payload: dict, source_id: str, portable_id: str) -> None:
    for principal in payload.get("principals", []):
        if principal.get("id") == source_id:
            principal["id"] = portable_id
    for member in payload.get("members", []):
        principal = member.get("principal") or {}
        if principal.get("id") == source_id:
            principal["id"] = portable_id
    for entity in payload.get("entities", []):
        if entity.get("controller_principal_id") == source_id:
            entity["controller_principal_id"] = portable_id
    for event in payload.get("ledger_events", []):
        if event.get("sender_principal_id") == source_id:
            event["sender_principal_id"] = portable_id
        event["visible_to"] = [
            portable_id if str(principal_id) == source_id else principal_id
            for principal_id in event.get("visible_to") or []
        ]


def test_game_save_export_import_conflict_replace_and_player_state(
    integration_stack, postgres_dsn
):
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
                (
                    str(uuid.uuid4()),
                    CAMPAIGN_ID,
                    SESSION_ID,
                    PLAYER_ID,
                    PLAYER_ID,
                    "save-roundtrip-event",
                ),
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

        payload = decrypt_save(blob, passphrase=PASSPHRASE, expected_kind="game")
        portable_player_id = str(uuid.uuid4())
        _rewrite_principal_id(payload, PLAYER_ID, portable_player_id)
        assert any(
            principal["id"] == portable_player_id for principal in payload["principals"]
        )
        portable_blob = encrypt_save(payload, kind="game", passphrase=PASSPHRASE)

        wrong = client.post(
            "/api/saves/game/import",
            data=_upload(portable_blob, passphrase="wrong-passphrase"),
            content_type="multipart/form-data",
        )
        assert wrong.status_code == 400
        assert "Decryption failed" in wrong.get_json()["error"]

        conflict = client.post(
            "/api/saves/game/import",
            data=_upload(portable_blob, replace=False),
            content_type="multipart/form-data",
        )
        assert conflict.status_code == 409
        assert conflict.get_json()["conflict"] is True

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE state.entities SET name = 'Broken Roundtrip Name' WHERE id = %s",
                (PC_ID,),
            )
    finally:
        conn.close()

    with app.test_client() as client:
        restored = client.post(
            "/api/saves/game/import",
            data=_upload(portable_blob, replace=True),
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

    assert payload["ledger_events"]
    assert all("visible_to" in event for event in payload["ledger_events"])

    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.principal_id', %s, true)", (PLAYER_ID,))
            cur.execute(
                """
                SELECT sender_principal_id,
                       %s::uuid = ANY(visible_to) AS contains_local_player,
                       %s::uuid = ANY(visible_to) AS contains_portable_player
                FROM ledger.session_ledger
                WHERE idempotency_key = 'save-roundtrip-event'
                """,
                (PLAYER_ID, portable_player_id),
            )
            sender_principal_id, contains_local, contains_portable = cur.fetchone()
    finally:
        conn.close()

    assert str(sender_principal_id) == PLAYER_ID
    assert contains_local is True
    assert contains_portable is False


def test_program_save_exports_clear_keys_and_import_reencrypts(
    integration_stack, postgres_dsn
):
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
    api_keys = next(
        row for row in payload["global_settings"] if row["key"] == "api_keys"
    )
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
            cur.execute(
                "SELECT value FROM state.global_settings WHERE key = 'api_keys'"
            )
            value = cur.fetchone()[0]
    finally:
        conn.close()

    assert value["openrouter"].startswith("vault:v1:")


def test_game_save_corruption_paths_return_clean_400s(integration_stack):
    del integration_stack
    with app.test_client() as client:
        exported = client.post(
            "/api/saves/game/export",
            json={"campaign_id": CAMPAIGN_ID, "passphrase": PASSPHRASE},
        )
        assert exported.status_code == 200
        blob = exported.data

        cases = [
            b"not-a-ttdm-file",
            b"ttdm-save:v1\n{bad-json\nbody",
            blob[:40],
            _rewrite_header(blob, format="WRONG_FORMAT"),
            _rewrite_header(blob, version=999),
            _rewrite_header(blob, schema_version=999),
            encrypt_save(
                {"global_settings": []}, kind="program", passphrase=PASSPHRASE
            ),
        ]
        for case in cases:
            response = client.post(
                "/api/saves/game/import",
                data=_upload(case, replace=True),
                content_type="multipart/form-data",
            )
            assert response.status_code == 400
            body = response.get_json()
            assert "error" in body
            assert "Traceback" not in str(body)


def test_game_save_roundtrip_preserves_rag_metadata_and_profiles(
    integration_stack, postgres_dsn
):
    del integration_stack
    profile_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO state.rag_embedding_profiles (
                    id, campaign_id, provider, embedding_model, vector_dim,
                    signature, qdrant_collection, active
                )
                VALUES (%s, %s, 'lmstudio', 'bge-small-en', 384, %s, %s, true)
                ON CONFLICT (campaign_id, signature) DO UPDATE
                SET embedding_model = EXCLUDED.embedding_model
                """,
                (
                    profile_id,
                    CAMPAIGN_ID,
                    f"qa{profile_id[:6]}",
                    f"qa_{profile_id[:6]}",
                ),
            )
            cur.execute(
                """
                INSERT INTO state.rag_documents (
                    id, campaign_id, filename, storage_path, status,
                    enabled, embedding_profile_id, needs_reindex
                )
                VALUES (%s, %s, 'qa_lore.md', 'data/rag/qa_lore.md', 'READY',
                        true, %s, false)
                ON CONFLICT (id) DO NOTHING
                """,
                (doc_id, CAMPAIGN_ID, profile_id),
            )
            cur.execute(
                """
                INSERT INTO state.rag_chunks (
                    id, doc_id, campaign_id, chunk_id, page, text,
                    qdrant_point_id, metadata
                )
                VALUES (%s, %s, %s, 'chunk-1', 1, 'QA lore chunk',
                        'point-1', '{"visibility":"party"}'::jsonb)
                ON CONFLICT (doc_id, chunk_id) DO UPDATE
                SET text = EXCLUDED.text
                """,
                (chunk_id, doc_id, CAMPAIGN_ID),
            )
    finally:
        conn.close()

    with app.test_client() as client:
        exported = client.post(
            "/api/saves/game/export",
            json={"campaign_id": CAMPAIGN_ID, "passphrase": PASSPHRASE},
        )
        assert exported.status_code == 200
        payload = decrypt_save(
            exported.data, passphrase=PASSPHRASE, expected_kind="game"
        )
        assert any(row["id"] == profile_id for row in payload["rag_embedding_profiles"])
        assert any(row["id"] == doc_id for row in payload["rag_documents"])
        assert any(row["id"] == chunk_id for row in payload["rag_chunks"])

        restored = client.post(
            "/api/saves/game/import",
            data=_upload(exported.data, replace=True),
            content_type="multipart/form-data",
        )
        assert restored.status_code == 200

    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT filename FROM state.rag_documents WHERE id = %s", (doc_id,)
            )
            assert cur.fetchone()[0] == "qa_lore.md"
            cur.execute("SELECT text FROM state.rag_chunks WHERE id = %s", (chunk_id,))
            assert cur.fetchone()[0] == "QA lore chunk"
    finally:
        conn.close()
