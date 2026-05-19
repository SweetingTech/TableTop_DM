import pytest
import uuid

from app import app
from shared.db.connection import execute_one

pytestmark = pytest.mark.integration


CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "66666666-6666-6666-6666-666666666661"


def test_campaign_members_can_create_local_player(integration_stack):
    del integration_stack
    with app.test_client() as client:
        response = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/members",
            json={
                "display_name": "QA Regression Player",
                "auth_subject": "test:qa-regression-player",
                "role": "PLAYER",
            },
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["membership"]["role"] == "PLAYER"
    assert body["join_hint"].startswith("/game?principal_id=")


def test_campaign_can_create_active_encounter_from_session_characters(integration_stack):
    del integration_stack
    campaign_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    entity_id = str(uuid.uuid4())
    gm_id = str(uuid.uuid4())
    execute_one(
        """
        INSERT INTO state.campaigns (id, slug, name, status, mode)
        VALUES (%s, %s, 'QA Encounter Regression', 'ACTIVE', 'EXPLORATION')
        RETURNING id
        """,
        (campaign_id, f"qa-encounter-{campaign_id[:8]}"),
    )
    execute_one(
        """
        INSERT INTO state.sessions (id, campaign_id, status)
        VALUES (%s, %s, 'ACTIVE')
        RETURNING id
        """,
        (session_id, campaign_id),
    )
    execute_one(
        """
        INSERT INTO state.principals (id, principal_type, display_name, auth_subject, is_active)
        VALUES (%s, 'HUMAN', 'QA GM', %s, true)
        RETURNING id
        """,
        (gm_id, f"test:qa-gm-{gm_id[:8]}"),
    )
    execute_one(
        """
        INSERT INTO state.campaign_members (campaign_id, principal_id, role)
        VALUES (%s, %s, 'GM')
        RETURNING principal_id
        """,
        (campaign_id, gm_id),
    )
    execute_one(
        """
        INSERT INTO state.entities (
            id, campaign_id, entity_type, name, public_sheet, secret_sheet,
            hp_current, hp_max, ac, speed, controlled_by
        )
        VALUES (%s, %s, 'PC', 'QA Encounter PC', '{}'::jsonb, '{}'::jsonb, 10, 10, 10, 30, 'PLAYER')
        RETURNING id
        """,
        (entity_id, campaign_id),
    )
    execute_one(
        """
        INSERT INTO state.session_characters (session_id, entity_id, status)
        VALUES (%s, %s, 'ACTIVE')
        RETURNING session_id
        """,
        (session_id, entity_id),
    )
    with app.test_client() as client:
        response = client.post(
            f"/api/campaigns/{campaign_id}/encounters",
            query_string={"principal_id": gm_id, "join_token": f"dm-smoke-join-{gm_id}"},
            json={"session_id": session_id},
        )
        assert response.status_code == 200
        encounter = response.get_json()["encounter"]

        slots = client.get(f"/api/encounters/{encounter['id']}/slots")

    assert encounter["status"] == "ACTIVE"
    assert slots.status_code == 200
    assert len(slots.get_json()) >= 1


def test_dm_recap_falls_back_to_visible_ledger_events(integration_stack):
    del integration_stack
    from services.session_intel.recap import generate_recap

    event_id = str(uuid.uuid4())
    execute_one(
        """
        INSERT INTO ledger.session_ledger (
            event_id, event_version, contract_version, type, campaign_id, session_id,
            sender_principal_id, payload, visible_to, domain_tags, idempotency_key
        ) VALUES (%s, 1, 1, 'NARRATION', %s, %s, %s, %s::jsonb, ARRAY[%s]::uuid[], ARRAY['qa'], %s)
        RETURNING event_id
        """,
        (
            event_id,
            CAMPAIGN_ID,
            SESSION_ID,
            "22222222-2222-2222-2222-222222222221",
            '{"message":"The party crossed the QA bridge.","visibility":"party"}',
            "22222222-2222-2222-2222-222222222222",
            str(uuid.uuid4()),
        ),
    )

    recap = generate_recap(uuid.UUID(SESSION_ID), uuid.UUID(CAMPAIGN_ID), "dm")

    assert "QA bridge" in recap


def test_ai_generate_character_default_mode_persists_entity(integration_stack, monkeypatch):
    del integration_stack

    class DummyLLM:
        def __init__(self, **_kwargs):
            pass

        def generate_structured(self, *_args, **_kwargs):
            return {
                "name": "QA Saved Ranger",
                "entity_type": "PC",
                "controlled_by": "PLAYER",
                "hp_max": 11,
                "public_sheet": {
                    "race": "Elf",
                    "class": "Ranger",
                    "level": 1,
                    "background": "Outlander",
                    "attributes": {
                        "strength": 10,
                        "dexterity": 16,
                        "constitution": 12,
                        "intelligence": 11,
                        "wisdom": 14,
                        "charisma": 9,
                    },
                    "armor_class": 14,
                    "speed": 30,
                    "skills": ["Survival", "Perception"],
                    "languages": ["Common", "Elvish"],
                    "personality": {
                        "traits": "Quiet and watchful.",
                        "ideals": "Protect the lost.",
                        "bonds": "Owes a debt to the forest.",
                        "flaws": "Distrusts cities.",
                        "goals": "Find the vanished trail.",
                    },
                    "backstory": "A scout from the old woods.",
                },
                "secret_sheet": {
                    "secrets": "Knows a forbidden pass.",
                    "plot_hooks": "A rival hunter follows them.",
                    "balance_notes": "Starter character.",
                },
                "tags": ["qa", "generated"],
                "ac": 14,
                "speed": 30,
            }

    monkeypatch.setattr("services.llm.adapter.LLMAdapter", DummyLLM)

    with app.test_client() as client:
        response = client.post(
            f"/api/campaigns/{CAMPAIGN_ID}/characters/generate",
            json={"concept": "elven ranger qa"},
        )

    assert response.status_code == 201
    body = response.get_json()
    assert body["id"]
    assert body["name"] == "QA Saved Ranger"
    assert body["public_sheet"]["x"] == 0
    assert body["public_sheet"]["y"] == 0
