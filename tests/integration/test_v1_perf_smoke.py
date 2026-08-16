from __future__ import annotations

import time
import uuid

import pytest

from app import app, socketio
from services.realtime.broadcaster import BroadcastEnvelope, broadcast_game_event

pytestmark = pytest.mark.integration

CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"
PLAYER_ID = "22222222-2222-2222-2222-222222222222"
DM_ID = "22222222-2222-2222-2222-222222222221"


def _elapsed_ms(fn):
    start = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - start) * 1000


def _best_ms(fn, *, attempts: int = 3):
    result = None
    samples = []
    for _ in range(attempts):
        result, elapsed = _elapsed_ms(fn)
        samples.append(elapsed)
    return result, min(samples)


def test_v1_perf_smoke_core_local_budgets(integration_stack):
    del integration_stack
    with app.test_client() as client:
        response, player_state_ms = _best_ms(
            lambda: client.get(
                f"/api/sessions/{SESSION_ID}/player_state",
                query_string={"principal_id": PLAYER_ID},
            )
        )
        assert response.status_code == 200

        response, rag_ms = _best_ms(
            lambda: client.post(
                f"/api/campaigns/{CAMPAIGN_ID}/rag/query",
                json={"query": "demo lore", "top_k": 1},
            )
        )
        assert response.status_code in {200, 400}
        assert "Traceback" not in response.get_data(as_text=True)

        response, save_ms = _best_ms(
            lambda: client.post(
                "/api/saves/game/export",
                json={"campaign_id": CAMPAIGN_ID, "passphrase": "perf-smoke"},
            )
        )
        assert response.status_code == 200

    dm = socketio.test_client(app)
    player = socketio.test_client(app)
    dm.emit(
        "join_campaign",
        {
            "campaign_id": CAMPAIGN_ID,
            "session_id": SESSION_ID,
            "principal_id": DM_ID,
        },
    )
    player.emit(
        "join_campaign",
        {
            "campaign_id": CAMPAIGN_ID,
            "session_id": SESSION_ID,
            "principal_id": PLAYER_ID,
        },
    )
    dm.get_received()
    player.get_received()
    _, fanout_ms = _elapsed_ms(
        lambda: broadcast_game_event(
            BroadcastEnvelope(
                event_id=str(uuid.uuid4()),
                campaign_id=CAMPAIGN_ID,
                session_id=SESSION_ID,
                event_type="game_event",
                payload={"message": "perf smoke"},
                visibility="public",
            )
        )
    )
    assert any(item["name"] == "game_event" for item in player.get_received())

    assert player_state_ms < 300
    assert fanout_ms < 150
    assert rag_ms < 1000
    assert save_ms < 5000
