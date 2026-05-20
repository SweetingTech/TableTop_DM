import uuid

import pytest

from app import app, socketio
from services.realtime.broadcaster import BroadcastEnvelope, broadcast_game_event

pytestmark = pytest.mark.integration


CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"
DM_ID = "22222222-2222-2222-2222-222222222221"
PLAYER_A_ID = "22222222-2222-2222-2222-222222222222"
PLAYER_B_ID = "22222222-2222-2222-2222-222222222223"
PC_A_ID = "33333333-3333-3333-3333-333333333331"
PC_B_ID = "33333333-3333-3333-3333-333333333332"
MAP_A = "44444444-4444-4444-4444-444444444441"
MAP_B = "44444444-4444-4444-4444-444444444442"


def _client(principal_id: str):
    client = socketio.test_client(app)
    assert client.is_connected()
    client.get_received()
    client.emit(
        "join_campaign",
        {
            "campaign_id": CAMPAIGN_ID,
            "session_id": SESSION_ID,
            "principal_id": principal_id,
        },
    )
    received = client.get_received()
    assert any(item["name"] == "joined" for item in received), received
    return client


def _event_names(client) -> list[str]:
    return [item["name"] for item in client.get_received()]


def _prepare_spatial_state(postgres_dsn: str) -> None:
    import psycopg2

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO state.maps (id, campaign_id, name, width, height, grid_size, kind)
                VALUES (%s, %s, 'Tavern Room', 20, 20, 5, 'ROOM')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """,
                (MAP_B, CAMPAIGN_ID),
            )
            cur.execute(
                """
                UPDATE state.entities
                SET current_map_id = %s, public_sheet = jsonb_set(jsonb_set(public_sheet, '{x}', '5'), '{y}', '5')
                WHERE id = %s
                """,
                (MAP_A, PC_A_ID),
            )
            cur.execute(
                """
                UPDATE state.entities
                SET current_map_id = %s, public_sheet = jsonb_set(jsonb_set(public_sheet, '{x}', '5'), '{y}', '5')
                WHERE id = %s
                """,
                (MAP_B, PC_B_ID),
            )
    finally:
        conn.close()


def test_dm_only_event_reaches_dm_and_no_player(integration_stack):
    del integration_stack
    dm = _client(DM_ID)
    player = _client(PLAYER_A_ID)

    broadcast_game_event(
        BroadcastEnvelope(
            event_id=str(uuid.uuid4()),
            campaign_id=CAMPAIGN_ID,
            session_id=SESSION_ID,
            event_type="game_event",
            payload={"message": "dm secret"},
            visibility="dm_only",
        )
    )

    assert _event_names(dm) == ["game_event"]
    assert _event_names(player) == []


def test_principal_scoped_event_reaches_listed_principal_and_dm_only(integration_stack):
    del integration_stack
    dm = _client(DM_ID)
    player_a = _client(PLAYER_A_ID)
    player_b = _client(PLAYER_B_ID)

    broadcast_game_event(
        BroadcastEnvelope(
            event_id=str(uuid.uuid4()),
            campaign_id=CAMPAIGN_ID,
            session_id=SESSION_ID,
            event_type="game_event",
            payload={"message": "for A"},
            visibility="principal_scoped",
            visible_to=[PLAYER_A_ID],
        )
    )

    assert _event_names(dm) == ["game_event"]
    assert _event_names(player_a) == ["game_event"]
    assert _event_names(player_b) == []


def test_public_event_reaches_public_players_and_dm_once(integration_stack):
    del integration_stack
    dm = _client(DM_ID)
    player_a = _client(PLAYER_A_ID)
    player_b = _client(PLAYER_B_ID)

    broadcast_game_event(
        BroadcastEnvelope(
            event_id=str(uuid.uuid4()),
            campaign_id=CAMPAIGN_ID,
            session_id=SESSION_ID,
            event_type="game_event",
            payload={"message": "public"},
            visibility="public",
        )
    )

    assert _event_names(dm) == ["game_event"]
    assert _event_names(player_a) == ["game_event"]
    assert _event_names(player_b) == ["game_event"]


def test_spatial_event_excludes_pc_on_another_map(integration_stack, postgres_dsn):
    del integration_stack
    _prepare_spatial_state(postgres_dsn)
    dm = _client(DM_ID)
    player_a = _client(PLAYER_A_ID)
    player_b = _client(PLAYER_B_ID)

    broadcast_game_event(
        BroadcastEnvelope(
            event_id=str(uuid.uuid4()),
            campaign_id=CAMPAIGN_ID,
            session_id=SESSION_ID,
            event_type="game_event",
            payload={"message": "near A"},
            visibility="spatial",
            map_id=MAP_A,
            x=5,
            y=5,
        )
    )

    assert _event_names(dm) == ["game_event"]
    assert _event_names(player_a) == ["game_event"]
    assert _event_names(player_b) == []


def test_explicit_visible_to_beats_spatial_widening(integration_stack, postgres_dsn):
    del integration_stack
    _prepare_spatial_state(postgres_dsn)
    dm = _client(DM_ID)
    player_a = _client(PLAYER_A_ID)
    player_b = _client(PLAYER_B_ID)

    broadcast_game_event(
        BroadcastEnvelope(
            event_id=str(uuid.uuid4()),
            campaign_id=CAMPAIGN_ID,
            session_id=SESSION_ID,
            event_type="game_event",
            payload={"message": "explicit only B"},
            visibility="spatial",
            visible_to=[PLAYER_B_ID],
            map_id=MAP_A,
            x=5,
            y=5,
        )
    )

    assert _event_names(dm) == ["game_event"]
    assert _event_names(player_a) == []
    assert _event_names(player_b) == ["game_event"]


def test_wrong_principal_join_is_rejected(integration_stack):
    del integration_stack
    client = socketio.test_client(app)
    client.get_received()
    client.emit(
        "join_campaign",
        {
            "campaign_id": CAMPAIGN_ID,
            "session_id": SESSION_ID,
            "principal_id": "99999999-9999-9999-9999-999999999999",
        },
    )
    received = client.get_received()
    assert any(item["name"] == "error" for item in received)
