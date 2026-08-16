from __future__ import annotations

from pathlib import Path
import uuid

import pytest

from app import app
from shared.db.connection import execute_one

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"
NPC_ID = "33333333-3333-3333-3333-333333333333"
PC_ID = "33333333-3333-3333-3333-333333333331"
NON_MEMBER_ID = "99999999-9999-4999-8999-999999999999"
DM_ID = "22222222-2222-2222-2222-222222222221"
PLAYER_ID = "22222222-2222-2222-2222-222222222222"
ENCOUNTER_ID = "55555555-5555-5555-5555-555555555551"
GM_QUERY = {"principal_id": DM_ID, "join_token": f"dm-smoke-join-{DM_ID}"}
PLAYER_QUERY = {
    "principal_id": PLAYER_ID,
    "join_token": f"player-smoke-join-{PLAYER_ID}",
}


def test_route_auth_matrix_document_has_release_gate_columns():
    matrix = (ROOT / "docs" / "release" / "1.0-route-auth-matrix.md").read_text(
        encoding="utf-8"
    )
    for column in (
        "Anonymous",
        "GM",
        "Player",
        "Campaign membership",
        "Session membership",
        "Principal scoped",
        "Visibility filtered",
        "DM-only risk",
        "Test coverage",
    ):
        assert column in matrix
    for family in (
        "Player state",
        "Realtime join",
        "Continuity/recaps",
        "Save/load",
        "Global/API settings",
    ):
        assert family in matrix


def test_principal_scoped_routes_reject_anonymous_and_non_member(integration_stack):
    del integration_stack
    with app.test_client() as client:
        anonymous_state = client.get(f"/api/sessions/{SESSION_ID}/player_state")
        assert anonymous_state.status_code == 401

        non_member_state = client.get(
            f"/api/sessions/{SESSION_ID}/player_state",
            query_string={"principal_id": NON_MEMBER_ID},
        )
        assert non_member_state.status_code == 403

        anonymous_memory = client.get(
            f"/api/campaigns/{CAMPAIGN_ID}/npc_memory/{NPC_ID}"
        )
        assert anonymous_memory.status_code == 401

        non_member_join = client.post(
            f"/api/sessions/{SESSION_ID}/join",
            json={"principal_id": NON_MEMBER_ID},
        )
        assert non_member_join.status_code == 403


def test_dm_only_game_routes_reject_anonymous_and_players(integration_stack):
    del integration_stack
    with app.test_client() as client:
        anonymous_encounter = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/encounters",
            json={"session_id": SESSION_ID},
        )
        player_encounter = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/encounters",
            query_string={
                "principal_id": PLAYER_ID,
                "join_token": f"player-smoke-join-{PLAYER_ID}",
            },
            json={"session_id": SESSION_ID},
        )
        anonymous_advance = client.post(f"/api/encounters/{ENCOUNTER_ID}/advance")
        player_advance = client.post(
            f"/api/encounters/{ENCOUNTER_ID}/advance",
            query_string={
                "principal_id": PLAYER_ID,
                "join_token": f"player-smoke-join-{PLAYER_ID}",
            },
        )
        anonymous_narrate = client.post(
            "/api/narrate", json={"campaign_id": CAMPAIGN_ID}
        )
        player_narrate = client.post(
            "/api/narrate",
            query_string={
                "principal_id": PLAYER_ID,
                "join_token": f"player-smoke-join-{PLAYER_ID}",
            },
            json={"campaign_id": CAMPAIGN_ID},
        )

    assert anonymous_encounter.status_code == 401
    assert player_encounter.status_code == 403
    assert anonymous_advance.status_code == 401
    assert player_advance.status_code == 403
    assert anonymous_narrate.status_code == 401
    assert player_narrate.status_code == 403


def test_gm_can_use_dm_only_game_routes_with_valid_local_identity(
    integration_stack, monkeypatch
):
    del integration_stack

    class DummyStateMachine:
        def advance_turn(self, _encounter_id):
            return {"current_turn_order": 2}

    class DummyNarrator:
        def __init__(self, **_kwargs):
            pass

        def narrate_event(self, **_kwargs):
            return "The scene continues."

    monkeypatch.setattr(
        "services.orchestrator.state_machine.StateMachine", DummyStateMachine
    )
    monkeypatch.setattr("services.llm.adapter.DMNarrationAgent", DummyNarrator)
    gm_query = {"principal_id": DM_ID, "join_token": f"dm-smoke-join-{DM_ID}"}

    with app.test_client() as client:
        encounter = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/encounters",
            query_string=gm_query,
            json={"session_id": SESSION_ID},
        )
        advance = client.post(
            f"/api/encounters/{ENCOUNTER_ID}/advance", query_string=gm_query
        )
        narrate = client.post(
            "/api/narrate",
            query_string=gm_query,
            json={"campaign_id": CAMPAIGN_ID, "event_data": {}, "context": "qa"},
        )

    assert encounter.status_code == 200
    assert advance.status_code == 200
    assert advance.get_json()["current_turn_order"] == 2
    assert narrate.status_code == 200
    assert narrate.get_json()["narration"] == "The scene continues."


def test_session_reads_require_principal_and_do_not_widen_visibility(integration_stack):
    del integration_stack
    dialogue_id = str(uuid.uuid4())
    whisper_id = str(uuid.uuid4())
    execute_one(
        """
        INSERT INTO ledger.session_ledger (
            event_id, event_version, contract_version, type, campaign_id, session_id,
            sender_principal_id, payload, visible_to, domain_tags, idempotency_key
        ) VALUES
          (%s, 1, 1, 'DIALOGUE', %s, %s, %s, %s::jsonb, ARRAY[%s]::uuid[], ARRAY['qa'], %s),
          (%s, 1, 1, 'GM_WHISPER', %s, %s, %s, %s::jsonb, ARRAY[%s]::uuid[], ARRAY['qa'], %s)
        RETURNING event_id
        """,
        (
            dialogue_id,
            CAMPAIGN_ID,
            SESSION_ID,
            DM_ID,
            '{"message":"QA visible NPC dialogue."}',
            PLAYER_ID,
            str(uuid.uuid4()),
            whisper_id,
            CAMPAIGN_ID,
            SESSION_ID,
            DM_ID,
            '{"message":"QA hidden GM whisper."}',
            DM_ID,
            str(uuid.uuid4()),
        ),
    )

    with app.test_client() as client:
        anonymous_chat = client.get(f"/api/sessions/{SESSION_ID}/chat_history")
        non_member_chat = client.get(
            f"/api/sessions/{SESSION_ID}/chat_history",
            query_string={"principal_id": NON_MEMBER_ID},
        )
        player_chat = client.get(
            f"/api/sessions/{SESSION_ID}/chat_history", query_string=PLAYER_QUERY
        )
        dm_chat = client.get(
            f"/api/sessions/{SESSION_ID}/chat_history", query_string=GM_QUERY
        )
        player_recap = client.get(
            f"/api/sessions/{SESSION_ID}/recap",
            query_string={**PLAYER_QUERY, "visibility": "dm"},
        )

    assert anonymous_chat.status_code == 401
    assert non_member_chat.status_code == 403

    player_rows = player_chat.get_json()
    player_messages = [r["payload"].get("message") for r in player_rows]
    assert "QA visible NPC dialogue." in player_messages
    assert "QA hidden GM whisper." not in player_messages

    dm_messages = [r["payload"].get("message") for r in dm_chat.get_json()]
    assert "QA visible NPC dialogue." in dm_messages
    assert "QA hidden GM whisper." in dm_messages

    assert player_recap.status_code == 200
    assert player_recap.get_json()["visibility"] != "dm"


def test_story_state_requires_principal_redacts_player_reads_and_requires_gm_for_writes(
    integration_stack,
):
    del integration_stack
    fake_updater = str(uuid.uuid4())

    with app.test_client() as client:
        anonymous_get = client.get(f"/api/sessions/{SESSION_ID}/story_state")
        player_get = client.get(
            f"/api/sessions/{SESSION_ID}/story_state", query_string=PLAYER_QUERY
        )
        anonymous_put = client.put(
            f"/api/sessions/{SESSION_ID}/story_state", json={"dm_private_notes": "leak"}
        )
        player_put = client.put(
            f"/api/sessions/{SESSION_ID}/story_state",
            query_string=PLAYER_QUERY,
            json={"dm_private_notes": "leak"},
        )
        gm_put = client.put(
            f"/api/sessions/{SESSION_ID}/story_state",
            query_string=GM_QUERY,
            json={
                "current_location": "QA Route Matrix",
                "dm_private_notes": "qa hidden history",
                "updated_by": fake_updater,
            },
        )
        anonymous_history = client.get(
            f"/api/sessions/{SESSION_ID}/story_state/history"
        )
        player_history = client.get(
            f"/api/sessions/{SESSION_ID}/story_state/history",
            query_string=PLAYER_QUERY,
        )
        gm_history = client.get(
            f"/api/sessions/{SESSION_ID}/story_state/history",
            query_string=GM_QUERY,
        )
        anonymous_add = client.post(
            f"/api/sessions/{SESSION_ID}/story_state/add_event",
            json={"description": "anonymous event"},
        )
        player_add = client.post(
            f"/api/sessions/{SESSION_ID}/story_state/add_event",
            query_string=PLAYER_QUERY,
            json={"description": "player event"},
        )
        gm_add = client.post(
            f"/api/sessions/{SESSION_ID}/story_state/add_event",
            query_string=GM_QUERY,
            json={"description": "QA GM-authored event"},
        )

    assert anonymous_get.status_code == 401
    assert player_get.status_code == 200
    player_story = player_get.get_json()
    assert "dm_notes" not in player_story
    assert "dm_private_notes" not in player_story
    assert anonymous_put.status_code == 401
    assert player_put.status_code == 403
    assert gm_put.status_code == 200
    assert gm_put.get_json()["updated_by"] == DM_ID
    assert anonymous_history.status_code == 401
    assert player_history.status_code == 200
    assert "qa hidden history" not in str(player_history.get_json())
    assert gm_history.status_code == 200
    assert "qa hidden history" in str(gm_history.get_json())
    assert anonymous_add.status_code == 401
    assert player_add.status_code == 403
    assert gm_add.status_code == 200
    assert gm_add.get_json()["updated_by"] == DM_ID


def test_campaign_mode_and_entity_mutations_require_validated_gm_identity(
    integration_stack, monkeypatch
):
    del integration_stack
    monkeypatch.setattr(
        "services.domain.maps.image_gen.generate_poi_image",
        lambda **_kwargs: "https://example.invalid/generated-poi.png",
    )
    map_record = execute_one(
        "SELECT id FROM state.maps WHERE campaign_id = %s ORDER BY created_at LIMIT 1",
        (CAMPAIGN_ID,),
    )
    assert map_record
    map_id = str(map_record["id"])

    with app.test_client() as client:
        anonymous_mode = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/mode", json={"mode": "SOCIAL"}
        )
        player_mode = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/mode",
            query_string=PLAYER_QUERY,
            json={"mode": "SOCIAL"},
        )
        gm_mode = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/mode",
            query_string=GM_QUERY,
            json={"mode": "COMBAT"},
        )

        anonymous_entity = client.put(f"/api/entities/{PC_ID}", json={"hp_current": 1})
        player_entity = client.put(
            f"/api/entities/{PC_ID}", query_string=PLAYER_QUERY, json={"hp_current": 1}
        )
        gm_entity = client.put(
            f"/api/entities/{PC_ID}", query_string=GM_QUERY, json={"hp_current": 7}
        )
        anonymous_delete = client.delete(f"/api/entities/{PC_ID}")
        player_delete = client.delete(
            f"/api/entities/{PC_ID}", query_string=PLAYER_QUERY
        )

        anonymous_campaign_mutations = [
            client.put(f"/api/campaigns/{CAMPAIGN_ID}", json={"mode": "SOCIAL"}),
            client.delete(f"/api/campaigns/{CAMPAIGN_ID}"),
            client.post(f"/api/campaigns/{CAMPAIGN_ID}/purge"),
            client.post(f"/api/campaigns/{CAMPAIGN_ID}/resume"),
            client.post(f"/api/campaigns/{CAMPAIGN_ID}/sessions"),
            client.post(
                f"/api/campaigns/{CAMPAIGN_ID}/entities",
                json={"name": "Anonymous NPC", "entity_type": "NPC"},
            ),
            client.post(f"/api/sessions/{SESSION_ID}/pause"),
            client.post(f"/api/sessions/{SESSION_ID}/resume"),
            client.post(f"/api/sessions/{SESSION_ID}/end"),
        ]
        player_campaign_mutations = [
            client.put(
                f"/api/campaigns/{CAMPAIGN_ID}",
                query_string=PLAYER_QUERY,
                json={"mode": "SOCIAL"},
            ),
            client.delete(f"/api/campaigns/{CAMPAIGN_ID}", query_string=PLAYER_QUERY),
            client.post(
                f"/api/campaigns/{CAMPAIGN_ID}/purge", query_string=PLAYER_QUERY
            ),
            client.post(
                f"/api/campaigns/{CAMPAIGN_ID}/resume", query_string=PLAYER_QUERY
            ),
            client.post(
                f"/api/campaigns/{CAMPAIGN_ID}/sessions",
                query_string=PLAYER_QUERY,
            ),
            client.post(
                f"/api/campaigns/{CAMPAIGN_ID}/entities",
                query_string=PLAYER_QUERY,
                json={"name": "Player NPC", "entity_type": "NPC"},
            ),
            client.post(f"/api/sessions/{SESSION_ID}/pause", query_string=PLAYER_QUERY),
            client.post(
                f"/api/sessions/{SESSION_ID}/resume", query_string=PLAYER_QUERY
            ),
            client.post(f"/api/sessions/{SESSION_ID}/end", query_string=PLAYER_QUERY),
        ]
        gm_campaign_update = client.put(
            f"/api/campaigns/{CAMPAIGN_ID}",
            query_string=GM_QUERY,
            json={"mode": "COMBAT"},
        )
        gm_campaign_resume = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/resume", query_string=GM_QUERY
        )

        anonymous_poi_create = client.post(
            f"/api/maps/{map_id}/pois",
            json={"x": 1, "y": 1, "kind": "SIGN", "name": "Anonymous POI"},
        )
        player_poi_create = client.post(
            f"/api/maps/{map_id}/pois",
            query_string=PLAYER_QUERY,
            json={"x": 1, "y": 1, "kind": "SIGN", "name": "Player POI"},
        )
        gm_poi = client.post(
            f"/api/maps/{map_id}/pois",
            query_string=GM_QUERY,
            json={"x": 1, "y": 1, "kind": "SIGN", "name": "QA Auth POI"},
        )
        assert gm_poi.status_code == 201
        poi_id = gm_poi.get_json()["id"]
        gm_poi_generate = client.post(
            f"/api/pois/{poi_id}/generate_image",
            query_string=GM_QUERY,
            json={"style_hint": "QA deterministic style"},
        )
        anonymous_poi_mutations = [
            client.put(f"/api/pois/{poi_id}", json={"name": "anonymous"}),
            client.delete(f"/api/pois/{poi_id}"),
            client.post(
                f"/api/pois/{poi_id}/image",
                json={"image_url": "https://example.invalid/anonymous.png"},
            ),
            client.post(f"/api/pois/{poi_id}/generate_image"),
            client.delete(f"/api/pois/{poi_id}/image"),
        ]
        player_poi_mutations = [
            client.put(
                f"/api/pois/{poi_id}",
                query_string=PLAYER_QUERY,
                json={"name": "player"},
            ),
            client.delete(f"/api/pois/{poi_id}", query_string=PLAYER_QUERY),
            client.post(
                f"/api/pois/{poi_id}/image",
                query_string=PLAYER_QUERY,
                json={"image_url": "https://example.invalid/player.png"},
            ),
            client.post(
                f"/api/pois/{poi_id}/generate_image", query_string=PLAYER_QUERY
            ),
            client.delete(f"/api/pois/{poi_id}/image", query_string=PLAYER_QUERY),
        ]
        gm_poi_image = client.post(
            f"/api/pois/{poi_id}/image",
            query_string=GM_QUERY,
            json={"image_url": "https://example.invalid/gm.png"},
        )
        gm_poi_update = client.put(
            f"/api/pois/{poi_id}",
            query_string=GM_QUERY,
            json={"name": "QA Auth POI Updated"},
        )
        gm_poi_image_delete = client.delete(
            f"/api/pois/{poi_id}/image", query_string=GM_QUERY
        )
        gm_poi_delete = client.delete(f"/api/pois/{poi_id}", query_string=GM_QUERY)

    assert anonymous_mode.status_code == 401
    assert player_mode.status_code == 403
    assert gm_mode.status_code == 200
    assert anonymous_entity.status_code == 401
    assert player_entity.status_code == 403
    assert gm_entity.status_code == 200
    assert gm_entity.get_json()["hp_current"] == 7
    assert anonymous_delete.status_code == 401
    assert player_delete.status_code == 403
    assert all(response.status_code == 401 for response in anonymous_campaign_mutations)
    assert all(response.status_code == 403 for response in player_campaign_mutations)
    assert gm_campaign_update.status_code == 200
    assert gm_campaign_resume.status_code == 200
    assert anonymous_poi_create.status_code == 401
    assert player_poi_create.status_code == 403
    assert gm_poi_generate.status_code == 200
    assert gm_poi_generate.get_json()["image_url"].endswith("generated-poi.png")
    assert all(response.status_code == 401 for response in anonymous_poi_mutations)
    assert all(response.status_code == 403 for response in player_poi_mutations)
    assert gm_poi_image.status_code == 200
    assert gm_poi_update.status_code == 200
    assert gm_poi_image_delete.status_code == 200
    assert gm_poi_delete.status_code == 200


def test_session_archives_require_validated_gm_identity(integration_stack):
    del integration_stack
    archive_id = None
    try:
        with app.test_client() as client:
            anonymous_archive = client.post(
                f"/api/sessions/{SESSION_ID}/archive",
                json={"summary": "anonymous archive"},
            )
            player_archive = client.post(
                f"/api/sessions/{SESSION_ID}/archive",
                query_string=PLAYER_QUERY,
                json={"summary": "player archive"},
            )
            gm_archive = client.post(
                f"/api/sessions/{SESSION_ID}/archive",
                query_string=GM_QUERY,
                json={
                    "summary": "QA protected archive",
                    "archived_by": PLAYER_ID,
                },
            )
            assert gm_archive.status_code == 200
            archive_id = gm_archive.get_json()["id"]

            anonymous_list = client.get(
                f"/api/campaigns/{CAMPAIGN_ID}/session_archives"
            )
            player_list = client.get(
                f"/api/campaigns/{CAMPAIGN_ID}/session_archives",
                query_string=PLAYER_QUERY,
            )
            gm_list = client.get(
                f"/api/campaigns/{CAMPAIGN_ID}/session_archives",
                query_string=GM_QUERY,
            )
            anonymous_detail = client.get(f"/api/session_archives/{archive_id}")
            player_detail = client.get(
                f"/api/session_archives/{archive_id}", query_string=PLAYER_QUERY
            )
            gm_detail = client.get(
                f"/api/session_archives/{archive_id}", query_string=GM_QUERY
            )
            anonymous_delete = client.delete(f"/api/session_archives/{archive_id}")
            player_delete = client.delete(
                f"/api/session_archives/{archive_id}", query_string=PLAYER_QUERY
            )
            gm_delete = client.delete(
                f"/api/session_archives/{archive_id}", query_string=GM_QUERY
            )

        assert anonymous_archive.status_code == 401
        assert player_archive.status_code == 403
        assert gm_archive.get_json()["archived_by"] == DM_ID
        assert anonymous_list.status_code == 401
        assert player_list.status_code == 403
        assert gm_list.status_code == 200
        assert any(row["id"] == archive_id for row in gm_list.get_json())
        assert anonymous_detail.status_code == 401
        assert player_detail.status_code == 403
        assert gm_detail.status_code == 200
        assert "chat_history" in gm_detail.get_json()
        assert "final_story_state" in gm_detail.get_json()
        assert anonymous_delete.status_code == 401
        assert player_delete.status_code == 403
        assert gm_delete.status_code == 200
    finally:
        if archive_id:
            execute_one(
                "DELETE FROM state.session_archives WHERE id = %s RETURNING id",
                (archive_id,),
            )
        execute_one(
            "UPDATE state.sessions SET is_archived = FALSE WHERE id = %s RETURNING id",
            (SESSION_ID,),
        )


def test_propose_validation_errors_do_not_expose_tracebacks_when_debug_is_off(
    integration_stack, monkeypatch
):
    del integration_stack
    monkeypatch.setenv("TTDM_DEBUG", "0")
    with app.test_client() as client:
        response = client.post("/api/propose", json={"action_type": "MOVE"})

    assert response.status_code == 400
    body = response.get_json()
    assert "error" in body
    assert "trace" not in body
    assert "E:\\TableTop_DM" not in str(body)
    assert "Traceback" not in str(body)


def test_strict_join_token_mode_accepts_revocable_join_codes(
    integration_stack, monkeypatch
):
    del integration_stack
    monkeypatch.setenv("TTDM_REQUIRE_JOIN_TOKEN", "1")

    with app.test_client() as client:
        missing_token = client.get(
            f"/api/sessions/{SESSION_ID}/player_state",
            query_string={"principal_id": PLAYER_ID},
        )
        assert missing_token.status_code == 401

        created = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/join_codes",
            query_string=GM_QUERY,
            json={
                "principal_id": PLAYER_ID,
                "session_id": SESSION_ID,
                "label": "QA strict token",
            },
        )
        assert created.status_code == 200
        code = created.get_json()["join_code"]
        assert code["join_token"].startswith("ttdm-")
        assert PLAYER_ID in code["join_url"]

        joined = client.post(
            f"/api/sessions/{SESSION_ID}/join",
            json={"principal_id": PLAYER_ID, "join_token": code["join_token"]},
        )
        assert joined.status_code == 200

        state = client.get(
            f"/api/sessions/{SESSION_ID}/player_state",
            query_string={"principal_id": PLAYER_ID, "join_token": code["join_token"]},
        )
        assert state.status_code == 200
        assert (
            state.get_json()["player_state"]["principal"]["principal_id"] == PLAYER_ID
        )

        listed = client.get(
            f"/api/campaigns/{CAMPAIGN_ID}/join_codes", query_string=GM_QUERY
        )
        assert listed.status_code == 200
        assert any(row["id"] == code["id"] for row in listed.get_json())

        revoked = client.delete(
            f"/api/campaigns/{CAMPAIGN_ID}/join_codes/{code['id']}",
            query_string=GM_QUERY,
        )
        assert revoked.status_code == 200

        rejected = client.post(
            f"/api/sessions/{SESSION_ID}/join",
            json={"principal_id": PLAYER_ID, "join_token": code["join_token"]},
        )
        assert rejected.status_code == 403
