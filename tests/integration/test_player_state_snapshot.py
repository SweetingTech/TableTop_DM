import json
import uuid

import psycopg2
import pytest

from app import app

pytestmark = pytest.mark.integration


CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"
DM_ID = "22222222-2222-2222-2222-222222222221"
PLAYER_A_ID = "22222222-2222-2222-2222-222222222222"
PLAYER_B_ID = "22222222-2222-2222-2222-222222222223"
PC_A_ID = "33333333-3333-3333-3333-333333333331"
PC_B_ID = "33333333-3333-3333-3333-333333333332"
NPC_ID = "33333333-3333-3333-3333-333333333333"
MAP_ID = "44444444-4444-4444-4444-444444444441"
NON_MEMBER_ID = "99999999-9999-4999-8999-999999999999"


@pytest.fixture
def player_state_seed(integration_stack, postgres_dsn: str):
    del integration_stack
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO state.principals (id, principal_type, display_name, auth_subject, is_active)
                VALUES (%s, 'HUMAN', 'Non Member', 'test:player-state-nonmember', true)
                ON CONFLICT (id) DO NOTHING
                """,
                (NON_MEMBER_ID,),
            )
            cur.execute(
                """
                INSERT INTO state.session_characters (session_id, entity_id, status)
                VALUES
                  (%s, %s, 'ACTIVE'),
                  (%s, %s, 'ACTIVE')
                ON CONFLICT (session_id, entity_id) DO UPDATE
                SET status = EXCLUDED.status, revived_at = NULL, death_details = NULL
                """,
                (SESSION_ID, PC_A_ID, SESSION_ID, PC_B_ID),
            )
            cur.execute(
                """
                UPDATE state.entities
                SET current_map_id = %s,
                    public_sheet = jsonb_set(jsonb_set(public_sheet, '{x}', '5'), '{y}', '5'),
                    secret_sheet = jsonb_set(COALESCE(secret_sheet, '{}'::jsonb), '{private_oath}', '"ash-bell"'::jsonb)
                WHERE id = %s
                """,
                (MAP_ID, PC_A_ID),
            )
            cur.execute(
                """
                UPDATE state.entities
                SET current_map_id = %s,
                    public_sheet = jsonb_set(jsonb_set(public_sheet, '{x}', '14'), '{y}', '14')
                WHERE id = %s
                """,
                (MAP_ID, PC_B_ID),
            )
            cur.execute(
                """
                UPDATE state.entities
                SET current_map_id = %s,
                    public_sheet = jsonb_set(jsonb_set(public_sheet, '{x}', '6'), '{y}', '5')
                WHERE id = %s
                """,
                (MAP_ID, NPC_ID),
            )
            cur.execute(
                """
                UPDATE state.story_state
                SET current_location = 'Eclipse Keep Entry Hall',
                    game_time = 'Morning',
                    active_npcs = %s::jsonb,
                    dm_notes = 'The bell is cursed.',
                    dm_private_notes = 'The scout is lying.'
                WHERE session_id = %s
                """,
                (
                    json.dumps(
                        [
                            {
                                "id": NPC_ID,
                                "name": "Ashfang Scout",
                                "notes": "Secret motive",
                            }
                        ]
                    ),
                    SESSION_ID,
                ),
            )
            cur.execute(
                """
                INSERT INTO state.map_pois (map_id, x, y, kind, name, description, is_hidden, metadata)
                VALUES
                  (%s, 6, 5, 'SIGN', 'Visible Rune', 'nearby', false, '{}'::jsonb),
                  (%s, 18, 18, 'TREASURE', 'Distant Cache', 'far away', false, '{}'::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (MAP_ID, MAP_ID),
            )
            cur.execute(
                """
                INSERT INTO state.proposed_story_patches (
                    id, campaign_id, session_id, source_kind, source_ref,
                    event_type, summary, entities, patch, evidence,
                    confidence, visibility, status
                ) VALUES
                  (%s, %s, %s, 'chat', '{}'::jsonb, 'unresolved_thread',
                   'DM-only Ashfang secret.', %s::jsonb, '{}'::jsonb, %s::jsonb,
                   0.9, 'dm_only', 'APPLIED'),
                  (%s, %s, %s, 'chat', '{}'::jsonb, 'unresolved_thread',
                   'Player A private Ashfang clue.', %s::jsonb, %s::jsonb, '[]'::jsonb,
                   0.9, 'principal_scoped', 'APPLIED')
                """,
                (
                    str(uuid.uuid4()),
                    CAMPAIGN_ID,
                    SESSION_ID,
                    json.dumps([NPC_ID]),
                    json.dumps(
                        [
                            {
                                "source_kind": "rag_chunk",
                                "filename": "ashfang_dm-only.md",
                                "visibility": "dm_only",
                                "excerpt": "Ashfang serves the bell.",
                            }
                        ]
                    ),
                    str(uuid.uuid4()),
                    CAMPAIGN_ID,
                    SESSION_ID,
                    json.dumps([NPC_ID]),
                    json.dumps({"visible_to": [PLAYER_A_ID]}),
                ),
            )
            cur.execute(
                """
                INSERT INTO ledger.session_ledger (
                    event_id, event_version, contract_version, type, campaign_id, session_id,
                    sender_principal_id, payload, visible_to, domain_tags, idempotency_key
                ) VALUES
                  (%s, 1, 1, 'NARRATION', %s, %s, %s, %s::jsonb, ARRAY[%s]::uuid[], ARRAY['spatial'], %s),
                  (%s, 1, 1, 'NARRATION', %s, %s, %s, %s::jsonb, ARRAY[%s]::uuid[], ARRAY['spatial'], %s)
                """,
                (
                    str(uuid.uuid4()),
                    CAMPAIGN_ID,
                    SESSION_ID,
                    DM_ID,
                    json.dumps(
                        {
                            "message": "Player A sees the rune.",
                            "map_id": MAP_ID,
                            "x": 6,
                            "y": 5,
                        }
                    ),
                    PLAYER_A_ID,
                    str(uuid.uuid4()),
                    str(uuid.uuid4()),
                    CAMPAIGN_ID,
                    SESSION_ID,
                    DM_ID,
                    json.dumps(
                        {
                            "message": "Player B hears distant glass.",
                            "map_id": MAP_ID,
                            "x": 14,
                            "y": 14,
                        }
                    ),
                    PLAYER_B_ID,
                    str(uuid.uuid4()),
                ),
            )
        yield
    finally:
        conn.close()


def _get_state(client, principal_id: str | None, **params):
    query = dict(params)
    if principal_id:
        query["principal_id"] = principal_id
    return client.get(f"/api/sessions/{SESSION_ID}/player_state", query_string=query)


def _state(response):
    assert response.status_code == 200
    return response.get_json()["player_state"]


def test_player_state_anonymous_rejected(player_state_seed):
    with app.test_client() as client:
        response = _get_state(client, None)

    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


def test_player_state_non_member_forbidden(player_state_seed):
    with app.test_client() as client:
        response = _get_state(client, NON_MEMBER_ID)

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_player_receives_only_own_controlled_entities_and_no_other_private_fields(
    player_state_seed,
):
    with app.test_client() as client:
        snapshot = _state(_get_state(client, PLAYER_A_ID))

    controlled_ids = {e["entity_id"] for e in snapshot["controlled_entities"]}
    assert controlled_ids == {PC_A_ID}
    assert snapshot["controlled_entities"][0]["private_sheet"] == {}
    visible_pc_b = [
        e for e in snapshot["visible_world"]["visible_entities"] if e["id"] == PC_B_ID
    ]
    assert visible_pc_b == []
    assert "secret_sheet" not in snapshot["visible_world"]["visible_entities"][0]


def test_player_cannot_see_dm_only_story_or_continuity(player_state_seed):
    with app.test_client() as client:
        snapshot = _state(_get_state(client, PLAYER_A_ID))

    narrative = snapshot["narrative_state"]
    assert "dm_notes" not in narrative
    assert all("notes" not in npc for npc in narrative["known_active_npcs"])
    summaries = {row["summary"] for row in narrative["visible_open_threads"]}
    assert "DM-only Ashfang secret." not in summaries
    assert "Player A private Ashfang clue." in summaries


def test_principal_scoped_event_appears_only_for_matching_principal(player_state_seed):
    with app.test_client() as client:
        player_a = _state(_get_state(client, PLAYER_A_ID))
        player_b = _state(_get_state(client, PLAYER_B_ID))

    a_messages = [
        e["payload"]["message"]
        for e in player_a["visible_world"]["visible_recent_events"]
    ]
    b_messages = [
        e["payload"]["message"]
        for e in player_b["visible_world"]["visible_recent_events"]
    ]
    assert "Player A sees the rune." in a_messages
    assert "Player A sees the rune." not in b_messages
    assert "Player B hears distant glass." in b_messages


def test_spatial_entity_and_poi_visibility(player_state_seed):
    with app.test_client() as client:
        snapshot = _state(_get_state(client, PLAYER_A_ID))

    visible_entity_ids = {
        e["id"] for e in snapshot["visible_world"]["visible_entities"]
    }
    visible_pois = {p["name"] for p in snapshot["visible_world"]["visible_pois"]}
    assert NPC_ID in visible_entity_ids
    assert PC_B_ID not in visible_entity_ids
    assert "Visible Rune" in visible_pois
    assert "Distant Cache" not in visible_pois


def test_dead_session_character_state_is_reflected(
    player_state_seed, postgres_dsn: str
):
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE state.session_characters SET status = 'DEAD' WHERE session_id = %s AND entity_id = %s",
                (SESSION_ID, PC_A_ID),
            )
        with app.test_client() as client:
            snapshot = _state(_get_state(client, PLAYER_A_ID))
    finally:
        conn.close()

    assert snapshot["controlled_entities"][0]["death_state"] == "DEAD"
    assert snapshot["controlled_entities"][0]["can_command"] is False


def test_legal_actions_disable_attack_when_no_visible_target_exists(
    player_state_seed, postgres_dsn: str
):
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE state.entities SET current_map_id = NULL WHERE id = %s",
                (NPC_ID,),
            )
        with app.test_client() as client:
            snapshot = _state(_get_state(client, PLAYER_A_ID))
    finally:
        conn.close()

    attack = next(
        a for a in snapshot["turn_state"]["legal_actions"] if a["action"] == "attack"
    )
    assert attack["enabled"] is False


def test_dm_can_inspect_simulated_player_view_and_player_cannot(player_state_seed):
    with app.test_client() as client:
        dm_response = _get_state(client, DM_ID, as_principal_id=PLAYER_A_ID)
        player_response = _get_state(client, PLAYER_A_ID, as_principal_id=PLAYER_B_ID)

    assert dm_response.status_code == 200
    assert (
        dm_response.get_json()["player_state"]["principal"]["principal_id"]
        == PLAYER_A_ID
    )
    assert player_response.status_code == 403


def test_snapshot_event_cursor_matches_visible_recent_events(player_state_seed):
    with app.test_client() as client:
        snapshot = _state(_get_state(client, PLAYER_A_ID))

    events = snapshot["visible_world"]["visible_recent_events"]
    cursor = snapshot["visible_world"]["event_cursor"]
    assert events
    assert cursor["last_ledger_id"] == events[-1]["event_id"]
    assert cursor["last_sequence"] == events[-1]["seq_id"]
