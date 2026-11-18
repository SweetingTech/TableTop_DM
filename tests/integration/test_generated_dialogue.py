from __future__ import annotations

import json

import psycopg2
import pytest

from kernel.api.app import create_app
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.cognition.test_dialogue_generation import dialogue_server
from tests.unit.kernel.test_speech_combat_behavior import prompt

pytestmark = pytest.mark.integration


def test_generated_receipt_restart_and_separate_worker_never_train_human_history(
    integration_stack, monkeypatch, tmp_path
):
    with dialogue_server(monkeypatch) as requests:
        app, (admin, player, card, path, run, target, base) = prepare(
            integration_stack, monkeypatch, tmp_path
        )
        prompt(admin, base, target, "dialogue-question")
        body = {"run_id": run, "idempotency_key": "generated-advice"}
        response = player.post(path + "/character-proposals", json=body)
        assert response.status_code == 200, response.get_json()
        receipt = response.get_json()
        assert receipt["dialogue"]["status"] == "GENERATED" and len(requests) == 1
        restarted = create_app(artifact_root=tmp_path)
        restored = restarted.test_client()
        restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
        assert restored.post(path + "/character-proposals", json=body).get_json() == receipt
        assert len(requests) == 1
        assert (
            restored.post(
                path + "/control",
                json={
                    "run_id": run,
                    "mode": "AUTONOMOUS",
                    "expected_epoch": 0,
                    "max_steps": 1,
                    "idempotency_key": "leave",
                },
            ).status_code
            == 200
        )
        worker = create_app(artifact_root=tmp_path)
        assert worker.extensions["character_runner"].run_once() == 1
        assert len(requests) == 2
        with (
            psycopg2.connect(integration_stack.admin_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT c.parameters,e.model_version,e.prompt_contract_version "
                "FROM sim.command_log c JOIN sim.events e "
                "ON (c.run_id,c.actor_id,c.idempotency_key)="
                "(e.run_id,e.actor_id,e.idempotency_key) "
                "WHERE c.run_id=%s AND c.decision_authorship='CHARACTER_POLICY'",
                (run,),
            )
            parameters, model, version = cursor.fetchone()
            assert model == "fixture-model-v1" and version == "character-dialogue-1.3.0"
            assert parameters["text"] == receipt["outcome"]["proposal"]["parameters"]["text"]
            assert parameters["claims"] == []
            cursor.execute(
                "SELECT count(*) FROM cognition.human_choice_evidence WHERE run_id=%s", (run,)
            )
            assert cursor.fetchone()[0] == 0


def test_outage_receipt_is_frozen_and_retry_never_reissues_http(
    integration_stack, monkeypatch, tmp_path
):
    with dialogue_server(monkeypatch, status=503) as requests:
        app, (admin, player, card, path, run, target, base) = prepare(
            integration_stack, monkeypatch, tmp_path
        )
        prompt(admin, base, target, "outage-question")
        body = {"run_id": run, "idempotency_key": "outage"}
        receipt = player.post(path + "/character-proposals", json=body).get_json()
        assert receipt["dialogue"]["status"] == "FALLBACK"
        restarted = create_app(artifact_root=tmp_path)
        restored = restarted.test_client()
        restored.set_cookie("ttdm_session", player.get_cookie("ttdm_session").value)
        assert restored.post(path + "/character-proposals", json=body).get_json() == receipt
        assert len(requests) == 1


@pytest.mark.parametrize("matches_cadence", [True, False])
def test_private_cadence_reaches_the_provider_and_invalid_length_uses_fallback(
    integration_stack, monkeypatch, tmp_path, matches_cadence
):
    def answer(content):
        cue = next(row for row in reversed(content["experiences"]) if row["speaker"] == "other")
        return {
            "text": (
                "Good to see you."
                if matches_cadence
                else "It has been good to see someone new come through town today."
            ),
            "sources": [cue["reference"]],
        }

    with dialogue_server(monkeypatch, answer) as requests:
        _, (admin, player, card, path, run, target, base) = prepare(
            integration_stack, monkeypatch, tmp_path
        )
        for i in range(3):
            prompt(admin, base, target, f"cadence-question-{i}")
            line = player.post(
                "/api/v2/commands",
                json={
                    **base,
                    "embodied_entity_id": card["entity_id"],
                    "command_type": "tabletop.dialogue.speak",
                    "parameters": {"text": "Hello there, friend.", "volume": "WHISPER"},
                    "idempotency_key": f"cadence-human-{i}",
                },
            )
            assert line.status_code == 200, line.get_json()
        prompt(admin, base, target, "cadence-final-question")
        response = player.post(
            path + "/character-proposals", json={"run_id": run, "idempotency_key": "cadence"}
        )
        assert response.status_code == 200, response.get_json()
        receipt = response.get_json()
        assert len(requests) == 1
        content = json.loads(requests[0]["messages"][-1]["content"])
        assert (content["cadence"], content["intent"], content["volume"]) == (
            "BRIEF",
            "GREET",
            "WHISPER",
        )
        assert "cadence_evidence_event_ids" not in content
        parameters = receipt["outcome"]["proposal"]["parameters"]
        assert parameters["volume"] == "WHISPER"
        assert parameters["text"] == ("Good to see you." if matches_cadence else "Hello.")
        assert receipt["dialogue"]["status"] == ("GENERATED" if matches_cadence else "FALLBACK")
