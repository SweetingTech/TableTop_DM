import uuid

import pytest
from app import app
from services.export.exporter import ReplayEngine

pytestmark = pytest.mark.unit


class DummyPrincipal:
    principal_id = uuid.UUID("22222222-2222-2222-2222-222222222221")
    role = "GM"

    def is_gm(self):
        return True

    def is_system(self):
        return False


class DummyProposal:
    def __init__(self, **kwargs):
        self.campaign_id = kwargs["campaign_id"]
        self.session_id = kwargs["session_id"]
        self.encounter_id = kwargs.get("encounter_id")
        self.proposer_principal_id = kwargs["proposer_principal_id"]


def test_player_move_token_proposal_returns_state_delta(monkeypatch):
    monkeypatch.setattr("shared.schemas.contracts.InterventionProposal", DummyProposal)
    monkeypatch.setattr(
        "shared.auth.principal.load_principal",
        lambda *_args, **_kwargs: DummyPrincipal(),
    )

    class Pipeline:
        def process_proposal(self, *_args, **_kwargs):
            return {
                "event_type": "STATE_DELTA",
                "payload": {"deltas": [{"table": "state.entities"}]},
            }

    monkeypatch.setattr("services.orchestrator.pipeline.OrchestratorPipeline", Pipeline)

    with app.test_client() as client:
        response = client.post(
            "/api/propose",
            json={
                "action_type": "MOVE",
                "principal_id": "22222222-2222-2222-2222-222222222222",
                "campaign_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "66666666-6666-6666-6666-666666666661",
                "params": {
                    "entity_id": "33333333-3333-3333-3333-333333333331",
                    "destination_x": 6,
                    "destination_y": 5,
                },
            },
        )

    assert response.status_code == 200
    assert response.get_json()["event_type"] == "STATE_DELTA"


def test_player_talk_to_npc_creates_dialogue_event(monkeypatch):
    class FakeEvent:
        def model_dump(self):
            return {"type": "DIALOGUE", "payload": {"dialogue": "Halt, intruder!"}}

    class ConversationManager:
        def __init__(self, *_args, **_kwargs):
            pass

        def handle_proximity_chat(self, **_kwargs):
            return [FakeEvent()]

    class LedgerWriter:
        def append_event(self, _event):
            return {"seq_id": 1}

    monkeypatch.setattr(
        "services.conversations.manager.ConversationManager", ConversationManager
    )
    monkeypatch.setattr("services.ledger.writer.LedgerWriter", LedgerWriter)

    with app.test_client() as client:
        response = client.post(
            "/api/chat",
            json={
                "campaign_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "66666666-6666-6666-6666-666666666661",
                "speaker_entity_id": "33333333-3333-3333-3333-333333333331",
                "speaker_principal_id": "22222222-2222-2222-2222-222222222222",
                "target_entity_id": "33333333-3333-3333-3333-333333333333",
                "message": "Talk",
            },
        )

    assert response.status_code == 200
    assert response.get_json()["events_created"] == 1


def test_gm_switches_mode_to_combat(monkeypatch):
    class StateMachine:
        def set_campaign_mode(self, _campaign_id, new_mode):
            return {"mode": new_mode.value}

    monkeypatch.setattr(
        "services.orchestrator.state_machine.StateMachine", StateMachine
    )

    with app.test_client() as client:
        response = client.post(
            "/api/campaigns/11111111-1111-1111-1111-111111111111/mode",
            query_string={
                "principal_id": "22222222-2222-2222-2222-222222222221",
                "join_token": "dm-smoke-join-22222222-2222-2222-2222-222222222221",
            },
            json={"mode": "COMBAT"},
        )

    assert response.status_code == 200
    assert response.get_json()["mode"] == "COMBAT"


def test_combat_round_intent_and_advance(monkeypatch):
    monkeypatch.setattr("shared.schemas.contracts.InterventionProposal", DummyProposal)
    monkeypatch.setattr(
        "shared.auth.principal.load_principal",
        lambda *_args, **_kwargs: DummyPrincipal(),
    )

    class Pipeline:
        def process_proposal(self, *_args, **_kwargs):
            return {
                "event_type": "STATE_DELTA",
                "payload": {
                    "deltas": [{"table": "state.entities", "domain_tags": ["combat"]}],
                    "tool_call": "resolve_attack",
                    "reaction_triggered": True,
                    "llm_calls": 0,
                },
            }

    class StateMachine:
        def advance_turn(self, _encounter_id):
            return {"current_turn_order": 2}

    monkeypatch.setattr("services.orchestrator.pipeline.OrchestratorPipeline", Pipeline)
    monkeypatch.setattr(
        "services.orchestrator.state_machine.StateMachine", StateMachine
    )

    with app.test_client() as client:
        propose = client.post(
            "/api/propose",
            json={
                "action_type": "ATTACK",
                "principal_id": "22222222-2222-2222-2222-222222222222",
                "campaign_id": "11111111-1111-1111-1111-111111111111",
                "session_id": "66666666-6666-6666-6666-666666666661",
                "encounter_id": "55555555-5555-5555-5555-555555555551",
                "params": {
                    "attacker_id": "33333333-3333-3333-3333-333333333331",
                    "target_id": "33333333-3333-3333-3333-333333333333",
                    "weapon": "sword",
                },
            },
        )
        advance = client.post(
            "/api/encounters/55555555-5555-5555-5555-555555555551/advance",
            query_string={
                "principal_id": "22222222-2222-2222-2222-222222222221",
                "join_token": "dm-smoke-join-22222222-2222-2222-2222-222222222221",
            },
        )

    assert propose.status_code == 200
    payload = propose.get_json()["payload"]
    assert payload["llm_calls"] == 0
    assert payload["reaction_triggered"] is True
    assert payload["tool_call"] == "resolve_attack"
    assert advance.status_code == 200
    assert advance.get_json()["current_turn_order"] == 2


def test_export_session_log_markdown(monkeypatch):
    class Exporter:
        def export_to_markdown(self, *_args, **_kwargs):
            return "# Session Log: Demo"

    monkeypatch.setattr("services.export.exporter.SessionExporter", Exporter)

    with app.test_client() as client:
        response = client.get(
            "/api/export/66666666-6666-6666-6666-666666666661",
            query_string={
                "principal_id": "22222222-2222-2222-2222-222222222222",
                "campaign_id": "11111111-1111-1111-1111-111111111111",
            },
        )

    assert response.status_code == 200
    assert response.mimetype == "text/markdown"
    assert "# Session Log" in response.get_data(as_text=True)


def test_replay_engine_verify_state_success(monkeypatch):
    engine = ReplayEngine()
    query_calls = []

    monkeypatch.setattr(
        ReplayEngine,
        "load_checkpoint",
        lambda self, _session_id, up_to_seq: {
            "events": [
                {
                    "seq_id": 1,
                    "type": "STATE_DELTA",
                    "payload": {
                        "deltas": [
                            {
                                "table": "state.entities",
                                "operation": "UPDATE",
                                "entity_id": "e1",
                                "changes": {"hp_current": 20},
                            }
                        ]
                    },
                }
            ]
        },
    )
    def fake_execute_query(query, params):
        query_calls.append((query, params))
        return [
            {
                "id": uuid.UUID("33333333-3333-3333-3333-333333333331"),
                "hp_current": 20,
                "hp_max": 28,
                "ac": 16,
            }
        ]

    monkeypatch.setattr("services.export.exporter.execute_query", fake_execute_query)

    result = engine.verify_state(
        uuid.UUID("66666666-6666-6666-6666-666666666661"),
        {
            "33333333-3333-3333-3333-333333333331": {
                "hp_current": 20,
                "hp_max": 28,
                "ac": 16,
            }
        },
    )

    assert result["verified"] is True
    assert result["mismatches"] == []
    assert len(query_calls) == 1
    assert "ANY(%s::uuid[])" in query_calls[0][0]
    assert query_calls[0][1] == (
        ["33333333-3333-3333-3333-333333333331"],
    )
