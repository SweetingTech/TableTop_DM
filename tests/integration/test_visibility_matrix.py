import json
import uuid

import psycopg2
import pytest

from services.session_intel.continuity import open_threads
from services.session_intel.recap import generate_recap, sources_for_recap

pytestmark = pytest.mark.integration


CAMPAIGN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = uuid.UUID("66666666-6666-6666-6666-666666666661")


def test_dm_only_rag_patch_stays_dm_only_across_recaps_and_continuity(
    integration_stack,
    postgres_dsn: str,
) -> None:
    del integration_stack
    patch_id = uuid.uuid4()
    evidence = [{
        "source_kind": "rag_chunk",
        "source_id": "black-bell-c1",
        "doc_id": "doc-black-bell",
        "chunk_id": "black-bell-c1",
        "filename": "black_bell_dm-only.md",
        "visibility": "dm_only",
        "excerpt": "The Black Bell binds the Ashen Choir.",
    }]

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
                ) VALUES (
                    %s, %s, %s, 'chat', '{}'::jsonb,
                    'unresolved_thread',
                    'The Black Bell implication remains unresolved.',
                    '[]'::jsonb,
                    %s::jsonb,
                    %s::jsonb,
                    0.900,
                    'dm_only',
                    'APPLIED'
                )
                """,
                (
                    str(patch_id),
                    str(CAMPAIGN_ID),
                    str(SESSION_ID),
                    json.dumps({"summary": "Black Bell binds the Ashen Choir"}),
                    json.dumps(evidence),
                ),
            )
    finally:
        conn.close()

    dm_recap = generate_recap(SESSION_ID, CAMPAIGN_ID, "dm")
    party_recap = generate_recap(SESSION_ID, CAMPAIGN_ID, "party")
    public_recap = generate_recap(SESSION_ID, CAMPAIGN_ID, "public")

    assert "Black Bell" in dm_recap
    assert "Black Bell" not in party_recap
    assert "Black Bell" not in public_recap

    assert sources_for_recap(SESSION_ID, "dm")[0]["filename"] == "black_bell_dm-only.md"
    assert sources_for_recap(SESSION_ID, "party") == []
    assert sources_for_recap(SESSION_ID, "public") == []

    assert any(str(row["id"]) == str(patch_id) for row in open_threads(CAMPAIGN_ID, visibility="dm"))
    assert all(str(row["id"]) != str(patch_id) for row in open_threads(CAMPAIGN_ID, visibility="party"))
