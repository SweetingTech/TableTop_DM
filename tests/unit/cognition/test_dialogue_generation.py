from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cognition.choice_state import SPEECH
from cognition.dialogue_generation import DialogueRequest
from cognition.openai_compatible import OpenAICompatibleDialogue, configured_dialogue
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import prompt, setup_scene
from tests.unit.kernel.test_tactical_choices import leave_and_run

pytestmark = pytest.mark.unit


@contextmanager
def dialogue_server(monkeypatch, answer=None, *, status=200):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            content = json.loads(payload["messages"][-1]["content"])
            incoming = next(
                (row for row in reversed(content["experiences"]) if row["speaker"] == "other"),
                content["experiences"][-1],
            )
            response = answer(content) if callable(answer) else answer
            response = (
                response
                if response is not None
                else {
                    "text": "I grew up on the docks; tell me which crossing worries you.",
                    "sources": [incoming["reference"]],
                }
            )
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": json.dumps(response)}}
                        ]
                    }
                ).encode()
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TTDM_DIALOGUE_MODE", "openai-compatible")
    monkeypatch.setenv("TTDM_DIALOGUE_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("TTDM_DIALOGUE_MODEL", "fixture-model-v1")
    monkeypatch.setenv("TTDM_DIALOGUE_API_KEY", "")
    try:
        yield requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_generated_speech_reaches_runner_and_receipt_retry_does_not_call_again(
    monkeypatch, tmp_path
):
    with dialogue_server(monkeypatch) as requests:
        app = _app(monkeypatch, tmp_path)
        admin, player, card, path, run, target, base = setup_scene(app)
        prompt(admin, base, target, "question")
        response = player.post(
            path + "/character-proposals", json={"run_id": run, "idempotency_key": "speech"}
        )
        assert response.status_code == 200, response.get_json()
        receipt = response.get_json()
        assert receipt["dialogue"]["status"] == "GENERATED"
        proposal = receipt["outcome"]["proposal"]
        assert proposal["parameters"]["text"] not in SPEECH.values()
        assert proposal["parameters"]["claims"] == []
        assert proposal["model_version"] == "fixture-model-v1"
        assert receipt["dialogue"]["source_event_ids"]
        assert (
            player.post(
                path + "/character-proposals", json={"run_id": run, "idempotency_key": "speech"}
            ).get_json()
            == receipt
        )
        assert len(requests) == 1
        sent = json.dumps(requests)
        for forbidden in (
            "SELF_PRIVATE_MAP",
            "world_id",
            "binding_id",
            "profile_id",
            "control_epoch",
            card["entity_id"],
            base["world_id"],
        ):
            assert forbidden not in sent
        event = leave_and_run(app, player, path, run, "leave")
        assert (
            event.event_type == "tabletop.dialogue.speak"
            and event.payload["text"] == proposal["parameters"]["text"]
        )
        assert not app.extensions["simulation"].human_decision_evidence


@pytest.mark.parametrize(
    "answer",
    [
        {"text": "We are in a simulation.", "sources": ["e0"]},
        {"text": "A reply.", "sources": ["hidden-dm-note"]},
        {"text": "A reply.", "sources": ["e0"], "claims": [{"secret": True}]},
        {"text": "*I slay everyone*", "sources": ["e0"]},
        {"text": "", "sources": ["e0"]},
    ],
)
def test_untrusted_speech_falls_back_without_executing_provider_fields(
    monkeypatch, tmp_path, answer
):
    with dialogue_server(monkeypatch, answer) as requests:
        app = _app(monkeypatch, tmp_path)
        admin, player, card, path, run, target, base = setup_scene(app)
        prompt(admin, base, target, "question")
        before = len(app.extensions["simulation"].events)
        response = player.post(
            path + "/character-proposals", json={"run_id": run, "idempotency_key": "bad"}
        )
        assert response.status_code == 200, response.get_json()
        receipt = response.get_json()
        assert receipt["dialogue"]["status"] == "FALLBACK"
        assert receipt["outcome"]["proposal"]["parameters"]["text"] in SPEECH.values()
        assert len(requests) == 1 and len(app.extensions["simulation"].events) == before


def test_provider_http_error_is_bounded_and_not_exposed(monkeypatch, tmp_path):
    with dialogue_server(monkeypatch, status=503) as requests:
        app = _app(monkeypatch, tmp_path)
        admin, player, card, path, run, target, base = setup_scene(app)
        prompt(admin, base, target, "question")
        event = leave_and_run(app, player, path, run, "leave")
        assert event.payload["text"] in SPEECH.values()
        assert len(requests) == 1


def test_off_does_not_select_a_provider_and_invalid_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("TTDM_DIALOGUE_MODE", "off")
    assert configured_dialogue() is None
    with pytest.raises(ValueError, match="configuration"):
        OpenAICompatibleDialogue("https://user:secret@example.test/v1", "fixture")


def test_total_deadline_and_inflight_limit_contain_stalled_transports(monkeypatch):
    release = threading.Event()
    workers = []

    def stalled(self, request):
        workers.append(threading.current_thread())
        release.wait(2)
        return {"text": "Late reply.", "sources": ["e0"]}

    monkeypatch.setattr(OpenAICompatibleDialogue, "_complete_http", stalled)
    provider = OpenAICompatibleDialogue("http://127.0.0.1/v1", "fixture", timeout=0.02)
    request = DialogueRequest(
        identity={},
        traits={},
        intent="ASK",
        volume="NORMAL",
        experiences=({"reference": "e0", "text": "Hello."},),
        nearby=(),
        seed=1,
    )
    started = time.monotonic()
    try:
        for _ in range(2):
            with pytest.raises(ValueError, match="deadline"):
                provider.complete(request)
        with pytest.raises(ValueError, match="busy"):
            provider.complete(request)
        assert time.monotonic() - started < 0.5
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)


def test_multiple_turns_include_own_previous_reply_and_current_experience(monkeypatch, tmp_path):
    def answer(content):
        incoming = next(
            row for row in reversed(content["experiences"]) if row["speaker"] == "other"
        )
        topic = "ferry" if "ferry" in incoming["text"] else "shelter"
        return {
            "text": f"About the {topic}, let us ask the sailors before setting out.",
            "sources": [incoming["reference"]],
        }

    with dialogue_server(monkeypatch, answer) as requests:
        app = _app(monkeypatch, tmp_path)
        admin, player, card, path, run, target, base = setup_scene(app)
        replies = []
        for index, question in enumerate(("Can we take the ferry?", "Where can we find shelter?")):
            response = admin.post(
                "/api/v2/commands",
                json={
                    **base,
                    "command_type": "tabletop.dialogue.speak",
                    "embodied_entity_id": target,
                    "parameters": {"text": question},
                    "idempotency_key": f"topic-{index}",
                },
            )
            assert response.status_code == 200
            advice = player.post(
                path + "/character-proposals",
                json={"run_id": run, "idempotency_key": f"turn-{index}"},
            ).get_json()
            assert advice["dialogue"]["status"] == "GENERATED"
            replies.append(advice["outcome"]["proposal"]["parameters"]["text"])
            assert (
                player.post("/api/v2/commands", json=advice["outcome"]["proposal"]).status_code
                == 200
            )
        assert replies[0] != replies[1]
        sent = json.loads(requests[-1]["messages"][-1]["content"])
        assert any(
            row["speaker"] == "self" and row["text"] == replies[0] for row in sent["experiences"]
        )
        assert sent["identity"]["backstory"] == "Raised by sailors."
