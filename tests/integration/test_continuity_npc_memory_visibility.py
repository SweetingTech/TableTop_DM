import json
import uuid

import psycopg2
import pytest

from app import app

pytestmark = pytest.mark.integration


CAMPAIGN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = uuid.UUID("66666666-6666-6666-6666-666666666661")
NPC_ID = "33333333-3333-3333-3333-333333333333"
DM_ID = "22222222-2222-2222-2222-222222222221"
PLAYER_A_ID = "22222222-2222-2222-2222-222222222222"
PLAYER_B_ID = "22222222-2222-2222-2222-222222222223"
NON_MEMBER_ID = "99999999-9999-4999-8999-999999999999"


def _insert_principal(conn, principal_id: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO state.principals (id, principal_type, display_name, auth_subject, is_active)
            VALUES (%s, 'HUMAN', 'Non Member', 'test:nonmember', true)
            ON CONFLICT (id) DO NOTHING
            """,
            (principal_id,),
        )


def _insert_patch(
    conn,
    *,
    summary: str,
    visibility: str,
    patch: dict | None = None,
    evidence: list[dict] | None = None,
    event_type: str = "unresolved_thread",
) -> str:
    patch_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO state.proposed_story_patches (
                id, campaign_id, session_id, source_kind, source_ref,
                event_type, summary, entities, patch, evidence,
                confidence, visibility, status
            ) VALUES (
                %s, %s, %s, 'chat', '{}'::jsonb,
                %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                0.900, %s, 'APPLIED'
            )
            """,
            (
                patch_id,
                str(CAMPAIGN_ID),
                str(SESSION_ID),
                event_type,
                summary,
                json.dumps([NPC_ID]),
                json.dumps(patch or {"summary": summary}),
                json.dumps(evidence or []),
                visibility,
            ),
        )
    return patch_id


@pytest.fixture
def seeded_npc_memory(integration_stack, postgres_dsn: str):
    del integration_stack
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        _insert_principal(conn, NON_MEMBER_ID)
        ids = {
            "public": _insert_patch(
                conn,
                summary="Ashfang Scout publicly fled the hall.",
                visibility="public",
            ),
            "party": _insert_patch(
                conn,
                summary="Ashfang Scout promised the party a map.",
                visibility="party",
                event_type="promise_made",
            ),
            "dm_only": _insert_patch(
                conn,
                summary="Ashfang Scout secretly serves the Black Bell.",
                visibility="dm_only",
                evidence=[
                    {
                        "source_kind": "rag_chunk",
                        "chunk_id": "black-bell-npc",
                        "filename": "black_bell_dm-only.md",
                        "visibility": "dm_only",
                        "excerpt": "Ashfang Scout carries orders from the Black Bell.",
                    }
                ],
            ),
            "scoped_a": _insert_patch(
                conn,
                summary="Ashfang Scout privately warned Player A.",
                visibility="principal_scoped",
                patch={"summary": "private warning", "visible_to": [PLAYER_A_ID]},
            ),
            "scoped_b": _insert_patch(
                conn,
                summary="Ashfang Scout privately warned Player B.",
                visibility="principal_scoped",
                patch={"summary": "private warning", "visible_to": [PLAYER_B_ID]},
            ),
        }
        yield ids
    finally:
        conn.close()


def _npc_memory(client, principal_id: str | None, visibility: str | None = None):
    query = {}
    if principal_id:
        query["principal_id"] = principal_id
    if visibility:
        query["visibility"] = visibility
    return client.get(
        f"/api/campaigns/{CAMPAIGN_ID}/npc_memory/{NPC_ID}",
        query_string=query,
    )


def _summaries(response):
    return {row["summary"] for row in response.get_json()}


def test_npc_memory_dm_can_see_dm_only_patch(seeded_npc_memory):
    with app.test_client() as client:
        response = _npc_memory(client, DM_ID, "dm")

    assert response.status_code == 200
    summaries = _summaries(response)
    assert "Ashfang Scout secretly serves the Black Bell." in summaries
    assert "Ashfang Scout privately warned Player A." in summaries
    assert "Ashfang Scout privately warned Player B." in summaries


def test_npc_memory_player_cannot_see_dm_only_patch_even_if_dm_requested(
    seeded_npc_memory,
):
    with app.test_client() as client:
        response = _npc_memory(client, PLAYER_A_ID, "dm")

    assert response.status_code == 200
    summaries = _summaries(response)
    assert "Ashfang Scout secretly serves the Black Bell." not in summaries
    assert "Ashfang Scout publicly fled the hall." in summaries
    assert "Ashfang Scout promised the party a map." in summaries


def test_npc_memory_principal_scoped_only_visible_to_matching_principal(
    seeded_npc_memory,
):
    with app.test_client() as client:
        response_a = _npc_memory(client, PLAYER_A_ID, "principal")
        response_b = _npc_memory(client, PLAYER_B_ID, "principal")

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    summaries_a = _summaries(response_a)
    summaries_b = _summaries(response_b)
    assert "Ashfang Scout privately warned Player A." in summaries_a
    assert "Ashfang Scout privately warned Player B." not in summaries_a
    assert "Ashfang Scout privately warned Player A." not in summaries_b
    assert "Ashfang Scout privately warned Player B." in summaries_b


def test_npc_memory_non_member_forbidden(seeded_npc_memory):
    with app.test_client() as client:
        response = _npc_memory(client, NON_MEMBER_ID, "principal")

    assert response.status_code == 403


def test_npc_memory_anonymous_rejected(seeded_npc_memory):
    with app.test_client() as client:
        response = _npc_memory(client, None, "principal")

    assert response.status_code == 401


def test_unresolved_promises_api_requires_member_and_filters_visibility(
    seeded_npc_memory,
):
    with app.test_client() as client:
        anonymous = client.get(f"/api/campaigns/{CAMPAIGN_ID}/unresolved_promises")
        player = client.get(
            f"/api/campaigns/{CAMPAIGN_ID}/unresolved_promises",
            query_string={"principal_id": PLAYER_A_ID, "visibility": "dm"},
        )

    assert anonymous.status_code == 401
    assert player.status_code == 200
    summaries = _summaries(player)
    assert "Ashfang Scout promised the party a map." in summaries
    assert "Ashfang Scout secretly serves the Black Bell." not in summaries


def test_npc_memory_matches_open_threads_visibility_semantics(seeded_npc_memory):
    with app.test_client() as client:
        memory = _npc_memory(client, PLAYER_A_ID, "principal")
        threads = client.get(
            f"/api/campaigns/{CAMPAIGN_ID}/open_threads",
            query_string={"principal_id": PLAYER_A_ID, "visibility": "principal"},
        )

    assert memory.status_code == 200
    assert threads.status_code == 200
    memory_summaries = _summaries(memory)
    thread_summaries = _summaries(threads)
    assert "Ashfang Scout secretly serves the Black Bell." not in memory_summaries
    assert "Ashfang Scout secretly serves the Black Bell." not in thread_summaries
    assert "Ashfang Scout privately warned Player A." in memory_summaries
    assert "Ashfang Scout privately warned Player A." in thread_summaries
    assert "Ashfang Scout privately warned Player B." not in memory_summaries
    assert "Ashfang Scout privately warned Player B." not in thread_summaries
