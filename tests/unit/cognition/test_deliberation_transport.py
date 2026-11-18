from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cognition.context import CharacterContext
from cognition.deliberation import DeliberationRequest, TypedDeliberationGateway
from cognition.models import Observation
from cognition.openai_compatible import OpenAICompatibleDeliberation, configured_deliberation
from domains.tabletop.character_actions import character_action_candidates
from domains.tabletop.spatial.scene import PerceivedEntity, PerceivedScene, SceneCoordinate
from kernel.api.app import create_app
from kernel.contracts import Actor, ActorKind, BranchKind
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


@pytest.fixture
def model_server():
    requests = []
    replies = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            status, result = replies.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests, replies
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def decision_request():
    return DeliberationRequest(
        identity_summary="A careful sailor.",
        situation={"experiences": ["The tide is turning."]},
        allowed_actions=("west", "east"),
        seed=42,
    )


def chat_reply(action, rationale="The tide is turning."):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"action": action, "rationale": rationale, "confidence": 0.8}
                    )
                },
            }
        ],
        "usage": {"prompt_tokens": 41, "completion_tokens": 9, "total_tokens": 50},
    }


def test_retry_uses_same_bounded_payload_and_records_real_usage(model_server):
    url, requests, replies = model_server
    replies.extend(
        [(503, {"error": "ignored provider response"}), (200, chat_reply("east", "RAW_MODEL_TEXT"))]
    )
    provider = OpenAICompatibleDeliberation(url, "configured-fixture", timeout=2)
    request = decision_request()
    outcome = TypedDeliberationGateway().decide(request, {"west": 2, "east": 1}, provider)
    assert outcome.used_model and outcome.response.action == "east"
    assert "RAW_MODEL_TEXT" not in outcome.model_dump_json()
    assert outcome.provider_attempts == 2 and outcome.model_version == "configured-fixture"
    assert outcome.usage is not None
    assert outcome.usage.model_dump() == {"prompt_tokens": 41, "completion_tokens": 9}
    assert len(requests) == 2 and requests[0] == requests[1]
    path, body = requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "configured-fixture"
    fiction = json.loads(body["messages"][1]["content"])
    assert fiction == request.model_dump(mode="json", exclude={"seed", "prompt_contract_version"})
    assert "seed" not in body and body["max_completion_tokens"] == 256


def test_unknown_action_and_oversized_context_fall_back_using_stable_codes(model_server):
    url, requests, replies = model_server
    replies.append((200, chat_reply("PROVIDER_PRIVATE_OUTPUT")))
    provider = OpenAICompatibleDeliberation(url, "configured-fixture")
    gateway = TypedDeliberationGateway()
    request = decision_request()
    scores = {"west": 2, "east": 1}
    denied = gateway.decide(request, scores, provider)
    assert denied.response.action == "west" and not denied.used_model
    assert denied.fallback_reason == "model_selected_disallowed_action"
    assert "PROVIDER_PRIVATE_OUTPUT" not in denied.model_dump_json()
    assert denied.usage is not None and denied.provider_attempts == 1

    oversized = request.model_copy(update={"situation": {"text": "wind " * 10_000}})
    bounded = gateway.decide(oversized, scores, provider)
    assert bounded.response.action == "west" and bounded.provider_attempts == 0
    assert bounded.fallback_reason == "provider_context_limit"
    assert len(requests) == 1


def test_deadline_limits_failed_model_attempts_and_configuration_is_opt_in(monkeypatch):
    monkeypatch.setenv("TTDM_DELIBERATION_MODE", "off")
    monkeypatch.setenv("TTDM_DIALOGUE_MODE", "openai-compatible")
    assert configured_deliberation() is None
    release = threading.Event()
    workers = []

    def stalled(*args):
        workers.append(threading.current_thread())
        release.wait(2)
        return json.dumps({"action": "east", "rationale": "Late.", "confidence": 0.4}), None

    monkeypatch.setattr(OpenAICompatibleDeliberation, "_chat", stalled)
    provider = OpenAICompatibleDeliberation("http://127.0.0.1/v1", "fixture", timeout=0.03)
    started = time.monotonic()
    try:
        result = TypedDeliberationGateway().decide(
            decision_request(), {"west": 2, "east": 1}, provider
        )
        assert time.monotonic() - started < 0.5
        assert result.response.action == "west" and result.provider_attempts == 1
        assert result.fallback_reason == "provider_deadline"
    finally:
        release.set()
        for worker in workers:
            worker.join(1)


def test_privileged_api_uses_only_a_provider_matching_the_runtime_kind(
    model_server, monkeypatch, tmp_path
):
    url, requests, replies = model_server
    replies.append((200, chat_reply("east")))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TTDM_OPERATOR_TOKEN", raising=False)
    monkeypatch.setenv("TTDM_DELIBERATION_MODE", "openai-compatible")
    monkeypatch.setenv("TTDM_DELIBERATION_BASE_URL", url)
    monkeypatch.setenv("TTDM_DELIBERATION_MODEL", "evaluation-fixture")
    monkeypatch.setenv("TTDM_DELIBERATION_RUNTIME_KIND", "LOCAL_LLM")
    app = create_app(artifact_root=tmp_path)
    client = app.test_client()
    ids = app.extensions["demo_ids"]
    scope = {key: str(ids[key]) for key in ("world_id", "branch_id", "run_id")}
    persona = client.post("/api/v2/personas/generate", json={"seed": 889}).get_json()
    runtime = f"/api/v2/entities/{ids['hero_id']}/runtime"
    decision = {
        **scope,
        "persona_id": persona["persona_id"],
        "actor_id": str(ids["actor_id"]),
        "embodied_entity_id": str(ids["hero_id"]),
        "seed": 42,
        "novel_or_ambiguous": True,
        "actions": [
            {
                "action": action,
                "command_type": "tabletop.spatial.move",
                "parameters": {"dx": dx, "dy": 0},
                "utility_factors": {"known_terrain": 1 if action == "west" else 0},
            }
            for action, dx in (("west", -1), ("east", 1))
        ],
    }
    events = len(app.extensions["simulation"].events)
    assert client.put(runtime, json={**scope, "runtime_kind": "HOSTED_LLM"}).status_code == 201
    fallback = client.post(
        "/api/v2/cognition/decide", json={**decision, "idempotency_key": "hosted"}
    )
    assert fallback.status_code == 201
    assert fallback.get_json()["trace"]["fallback_reason"] == "model_provider_unavailable"
    assert fallback.get_json()["trace"]["chosen_action"] == "west" and not requests
    assert client.put(runtime, json={**scope, "runtime_kind": "LOCAL_LLM"}).status_code == 200
    planned = client.post("/api/v2/cognition/decide", json={**decision, "idempotency_key": "local"})
    assert planned.status_code == 201, planned.get_json()
    assert planned.get_json()["trace"]["model_version"] == "evaluation-fixture"
    assert planned.get_json()["trace"]["chosen_action"] == "east" and len(requests) == 1
    assert len(app.extensions["simulation"].events) == events


def test_live_advice_uses_configured_provider_and_reuses_scoped_receipt(
    model_server, monkeypatch, tmp_path
):
    url, requests, replies = model_server
    replies.append((200, chat_reply("Try to take one step east")))
    monkeypatch.setenv("TTDM_DELIBERATION_MODE", "openai-compatible")
    monkeypatch.setenv("TTDM_DELIBERATION_BASE_URL", url)
    monkeypatch.setenv("TTDM_DELIBERATION_MODEL", "trusted-live-fixture")
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    events = len(app.extensions["simulation"].events)
    body = {"run_id": run, "idempotency_key": "configured-character-advice"}
    advice = player.post(path + "/character-proposals", json=body)
    assert advice.status_code == 200, advice.get_json()
    choice = advice.get_json()
    assert choice["outcome"]["tier"] == "LLM" and choice["committed"] is False
    assert choice["outcome"]["proposal"]["parameters"] == {"dx": 1, "dy": 0}
    assert player.post(path + "/character-proposals", json=body).get_json() == choice
    assert len(requests) == 1 and len(app.extensions["simulation"].events) == events
    fiction = requests[0][1]["messages"][1]["content"]
    assert run not in fiction and card["entity_id"] not in fiction
    spatial = json.loads(fiction)["situation"]["surroundings"]
    assert spatial and spatial[0]["position"]["area"] == "area-1"
    assert "zone_id" not in fiction and "apparent_type" not in fiction


def test_two_threats_bind_action_names_to_correct_fiction_references(model_server):
    body, nearby, distant = (uuid.UUID(int=id_number) for id_number in (100, 200, 10))

    def perceived(entity_id, name, x):
        return PerceivedEntity(
            entity_id=entity_id,
            name=name,
            position=SceneCoordinate(x=x, y=0),
            position_confidence=1,
            knowledge_state="VISIBLE",
            detail_level="INSPECTED",
            health=3 if entity_id == distant else 9,
            max_health=12,
            mana=4 if entity_id == body else None,
            attack_reach=2 if entity_id == body else None,
        )

    scene = PerceivedScene(
        observer_entity_id=body,
        world_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        projection_version=1,
        visible_zones=("world",),
        perceived_entities=(
            perceived(body, "Sailor", 0),
            perceived(nearby, "Armored raider", 1),
            perceived(distant, "Wounded scout", 2),
        ),
        recent_observations=(),
        available_viewpoints=(),
    )
    attacks = tuple(
        Observation(
            observer_entity_id=body,
            source_event_id=uuid.uuid4(),
            perceived_payload={"attacker_id": str(threat), "target_id": str(body)},
            confidence=1,
        )
        for threat in (nearby, distant)
    )
    actor = Actor(
        kind=ActorKind.AGENT,
        display_name="Fixture executor",
        capabilities=frozenset({"action.propose", "action.commit", "entity.act"}),
        controlled_entity_ids=frozenset({body}),
    )
    actions = character_action_candidates(
        scene, actor=actor, branch_kind=BranchKind.CANONICAL, observations=attacks
    )
    situation = CharacterContext(
        scene=scene, observations=attacks, beliefs=(), memories=(), actions=actions
    ).situation()
    choice = "Try an arcane bolt at perceived threat 2"
    url, requests, replies = model_server
    replies.append((200, chat_reply(choice)))
    request = DeliberationRequest(
        identity_summary="Defender of the harbor.",
        situation=situation,
        allowed_actions=tuple(action.action for action in actions),
        seed=42,
    )
    outcome = TypedDeliberationGateway().decide(
        request,
        dict.fromkeys(request.allowed_actions, 0.0),
        OpenAICompatibleDeliberation(url, "fixture"),
    )
    encoded = requests[0][1]["messages"][1]["content"]
    assert str(nearby) not in encoded and str(distant) not in encoded
    perceived_context = json.loads(encoded)["situation"]
    refs = {row["name"]: row["reference"] for row in perceived_context["surroundings"]}
    options = perceived_context["action_targets"]
    assert refs == {"Sailor": "self", "Armored raider": "subject-2", "Wounded scout": "subject-1"}
    assert options["Try a basic melee attack against perceived threat 1"] == refs["Armored raider"]
    assert options[choice] == refs["Wounded scout"]
    assert options["Try to mend my wounds"] == refs["Sailor"]
    selected = next(action for action in actions if action.action == outcome.response.action)
    assert outcome.used_model and selected.parameters["target_id"] == str(distant)
