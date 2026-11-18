from __future__ import annotations

import json
import time
import uuid

import psycopg2
import pytest

from cognition.projector import WorldEventProjector
from kernel.api.app import create_app
from tests.integration.test_speech_combat_behavior import prepare
from tests.unit.cognition.test_dialogue_generation import dialogue_server

pytestmark = pytest.mark.integration


def test_due_reply_waits_for_perception_and_commits_once_across_restart(
    integration_stack, monkeypatch, tmp_path
):
    monkeypatch.setenv("TTDM_DELIBERATION_MODE", "off")
    app, (admin, player, card, path, run, speaker, base) = prepare(
        integration_stack, monkeypatch, tmp_path
    )
    question = "When can we cross the harbor?"
    with monkeypatch.context() as patch:
        patch.setattr(app.extensions["simulation"], "subjective_projector", None)
        response = admin.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": speaker,
                "command_type": "tabletop.dialogue.speak",
                "parameters": {"text": question, "language": "common", "volume": "NORMAL"},
                "idempotency_key": "ask-about-the-harbor",
            },
        )
    assert response.status_code == 200, response.get_json()
    source = response.get_json()["event"]
    handed = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 2,
            "interval_ms": 100,
            "idempotency_key": "take-the-conversation",
        },
    )
    assert handed.status_code == 200, handed.get_json()

    def answer(request):
        cue = next(row for row in request["experiences"] if row["reference"] == request["reply_to"])
        assert cue["text"] == question
        return {"text": "Let's cross when the tide goes out.", "sources": [cue["reference"]]}

    def new_worker():
        worker = create_app(artifact_root=tmp_path).extensions["character_runner"]
        due = worker.controllers.due
        monkeypatch.setattr(
            worker.controllers, "due", lambda: tuple(row for row in due() if str(row.run_id) == run)
        )
        return worker

    def next_decision(worker):
        deadline = time.monotonic() + 4
        while not (due := worker.controllers.due()):
            assert time.monotonic() < deadline
            time.sleep(0.05)
        state = due[0]
        return worker.decisions.decide(
            state.scope, state.executor_actor_id, state.decision_key, state
        )

    projector = WorldEventProjector(integration_stack.database_url)
    topic = f"world.{base['world_id']}.branch.{base['branch_id']}"
    (pending,) = projector._claim(1, topic=topic)
    assert str(pending.event.event_id) == source["event_id"]
    with dialogue_server(monkeypatch, answer) as requests:
        assert new_worker().run_once() == 0
        assert not requests
        projector._process_claim(pending)
        restarted = new_worker()
        reply = next_decision(restarted)
        assert reply.reply is not None and reply.dialogue is not None
        assert reply.reply.source_event_id == uuid.UUID(source["event_id"])
        assert reply.reply.speaker_entity_id == uuid.UUID(speaker)
        assert reply.dialogue.source_event_ids == (uuid.UUID(source["event_id"]),)
        assert reply.outcome.proposal.causation_id == uuid.UUID(source["event_id"])
        assert reply.outcome.proposal.correlation_id == uuid.UUID(source["correlation_id"])
        assert reply.outcome.proposal.command_type == "tabletop.dialogue.speak"
        assert restarted.run_once() == 1 and len(requests) == 1
        projector.run_once(limit=1000)
        last_worker = new_worker()
        following = next_decision(last_worker)
        assert following.reply is None
        assert following.outcome.proposal.command_type != "tabletop.dialogue.speak"
        assert last_worker.run_once() == 1 and last_worker.run_once() == 0
        assert len(requests) == 1

    with psycopg2.connect(integration_stack.admin_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT payload,causation_id,correlation_id FROM sim.events "
            "WHERE run_id=%s AND embodied_entity_id=%s AND event_type='tabletop.dialogue.speak'",
            (run, card["entity_id"]),
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        payload, cause, correlation = rows[0]
        assert cause == source["event_id"] and correlation == source["correlation_id"]
        assert payload["text"] == "Let's cross when the tide goes out."
        assert payload["language"] == "common"
        assert payload["volume"] == reply.outcome.proposal.parameters["volume"]
        assert "source_observation_id" not in json.dumps(payload)
