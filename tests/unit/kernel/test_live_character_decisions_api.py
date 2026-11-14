from __future__ import annotations

import json
import uuid

import pytest

from cognition.engine import LayeredDecisionEngine
from cognition.models import Observation, RuntimeAssignment
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import PerceptionGrant, PerceptionOutcome, SensoryModality
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def test_trusted_proposal_is_pinned_private_idempotent_and_noncommitting(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    sim = app.extensions["simulation"]
    ids = app.extensions["demo_ids"]
    before = sim.states.get(ids["branch_id"]).version
    events = len(sim.events)
    captured = []
    decide = LayeredDecisionEngine.decide

    def spy(self, request):
        captured.append(request)
        return decide(self, request)

    monkeypatch.setattr(LayeredDecisionEngine, "decide", spy)
    body = {"run_id": run, "idempotency_key": "first-character-advice"}
    result = player.post(path + "/character-proposals", json=body)
    assert result.status_code == 200, result.get_json()
    receipt = result.get_json()
    assert receipt["execution_mode"] == "PROPOSAL_ONLY" and receipt["committed"] is False
    assert receipt["authorship"] == "CHARACTER_POLICY"
    assert len(captured) == 1 and captured[0].allow_llm is False
    assert captured[0].situation["identity"]["backstory"] == "Raised by sailors."
    assert "SELF_PRIVATE_MAP" in json.dumps(captured[0].situation)
    assert len(captured[0].actions) == 4
    assert captured[0].persona.purpose.value == "CHARACTER"
    assert receipt["outcome"]["proposal"]["command_type"] == "tabletop.spatial.move"
    assert len(sim.events) == events and sim.states.get(ids["branch_id"]).version == before
    assert player.post(path + "/character-proposals", json=body).get_json() == receipt
    assert len(captured) == 1
    assert (
        player.patch(
            f"/api/v2/player/characters/{card['character_id']}",
            json={"authored_identity": {"backstory": "An unbound later revision."}},
        ).status_code
        == 200
    )
    assert player.post(path + "/character-proposals", json=body).get_json() == receipt
    # Only the normal authorized kernel command path changes the world.
    proposal = receipt["outcome"]["proposal"]
    applied = player.post("/api/v2/commands", json=proposal)
    assert applied.status_code == 200, applied.get_json()
    assert player.post("/api/v2/commands", json=proposal).get_json() == applied.get_json()
    assert len(sim.events) == events + 1
    assert player.post(path + "/character-proposals", json=body).get_json() == receipt
    new = player.post(
        path + "/character-proposals", json={**body, "idempotency_key": "next-character-advice"}
    ).get_json()
    assert new["decision_id"] != receipt["decision_id"]
    assert new["seed"] != receipt["seed"] and new["context_hash"] != receipt["context_hash"]
    assert "An unbound later revision." not in json.dumps(captured[-1].situation)


@pytest.mark.parametrize(
    "field",
    ["situation", "actions", "seed", "persona_id", "allow_llm", "runtime_config", "actor_id"],
)
def test_proposal_rejects_caller_supplied_policy_inputs(monkeypatch, tmp_path, field):
    app = _app(monkeypatch, tmp_path)
    _, player, _, _, path, run, _ = setup_bound_character(app)
    response = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "extra", field: {}}
    )
    assert response.status_code == 400 and response.get_json()["error"] == "invalid_request"


def test_proposal_requires_body_control_binding_and_matching_scope(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, _, _, path, run, _ = setup_bound_character(app)
    body = {"run_id": run, "idempotency_key": "denied"}
    # Inspection authority alone never grants permission to advise another body.
    assert admin.post(path + "/character-proposals", json=body).status_code == 403
    _, other, _, _, _, _, _ = setup_bound_character(app)
    assert other.post(path + "/character-proposals", json=body).status_code == 403
    assert (
        player.post(
            path + "/character-proposals", json={**body, "run_id": str(uuid.uuid4())}
        ).status_code
        == 400
    )
    ids = app.extensions["demo_ids"]
    body_entity = next(
        iter(
            app.extensions["simulation"]
            .authority(ids["world_id"], ids["actor_id"])
            .controlled_entity_ids
        )
    )
    unbound = (
        f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}"
        f"/entities/{body_entity}/character-proposals"
    )
    assert admin.post(unbound, json=body).status_code == 400


def test_proposal_waits_for_frozen_subjective_observations(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    sim = app.extensions["simulation"]
    ids = app.extensions["demo_ids"]
    projector = sim.subjective_projector
    delayed = []
    sim.configure_subjective_projector(delayed.append)
    speech = player.post(
        "/api/v2/commands",
        json={
            "command_type": "tabletop.dialogue.speak",
            "world_id": card["world_id"],
            "branch_id": str(ids["branch_id"]),
            "run_id": run,
            "embodied_entity_id": card["entity_id"],
            "parameters": {"text": "Remember our promise."},
            "idempotency_key": "delayed-experience",
        },
    )
    assert speech.status_code == 200
    body = {"run_id": run, "idempotency_key": "after-experience"}
    pending = player.post(path + "/character-proposals", json=body)
    assert pending.status_code == 409
    assert pending.get_json()["error"] == "character_context_pending"
    assert str(delayed[0].event.event_id) not in json.dumps(pending.get_json())
    for receipt in delayed:
        projector(receipt)
    ready = player.post(path + "/character-proposals", json=body)
    assert ready.status_code == 200, ready.get_json()
    assert player.post(path + "/character-proposals", json=body).get_json() == ready.get_json()


def test_live_policy_excludes_hidden_operator_and_abandoned_branch_inputs(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    sim, minds, ids = (app.extensions[key] for key in ("simulation", "minds", "demo_ids"))
    entity = uuid.UUID(card["entity_id"])
    actor = uuid.UUID(player.get("/api/v2/auth/session").get_json()["user"]["actor_id"])
    record = sim.entities[(ids["branch_id"], entity)]
    sim.entities[(ids["branch_id"], entity)] = record.model_copy(
        update={"secret_state": {"plot": "HIDDEN_CANONICAL_FACT"}}
    )
    assignment = RuntimeAssignment(
        world_id=ids["world_id"],
        branch_id=ids["branch_id"],
        run_id=ids["run_id"],
        entity_id=entity,
        runtime_kind="HUMAN",
        runtime_config={"private": "PRIVATE_CONTROLLER_RULE"},
    )
    minds.set_runtime_assignment(assignment)
    observations = []
    for tag, branch, text in [
        ("director", ids["branch_id"], "OPERATOR_REVISION_NOTE"),
        ("dialogue", uuid.uuid4(), "ABANDONED_TIMELINE_FACT"),
    ]:
        event = EventEnvelopeV2(
            world_id=ids["world_id"],
            branch_id=branch,
            run_id=ids["run_id"],
            actor_id=actor,
            event_type="tabletop.dialogue.speak",
            visible_to=(actor,),
            correlation_id=uuid.uuid4(),
            domain_tags=(tag,),
            payload={"text": text},
        )
        observation = Observation(
            observer_entity_id=entity,
            source_event_id=event.event_id,
            perceived_payload={"text": text},
            confidence=1,
        )
        grant = PerceptionGrant(
            event_id=event.event_id,
            world_id=ids["world_id"],
            branch_id=branch,
            observer_entity_id=entity,
            modalities=(SensoryModality.SOUND,),
            outcome=PerceptionOutcome.DIRECT,
            confidence=1,
            allowed_payload_fields=("text",),
            resolver_version="test",
            spatial_context_hash="a" * 64,
        )
        sim.events[event.event_id] = event
        sim.perceptions[(event.event_id, entity)] = grant
        observations.append(observation)
    minds.restore(
        minds.get(entity, branch_id=ids["branch_id"]),
        branch_id=ids["branch_id"],
        observations=tuple(observations),
    )
    captured = []
    original = LayeredDecisionEngine.decide

    def spy(self, request):
        captured.append(request.situation)
        return original(self, request)

    monkeypatch.setattr(LayeredDecisionEngine, "decide", spy)
    response = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "no-omniscience"}
    )
    assert response.status_code == 200, response.get_json()
    fiction = json.dumps(captured)
    for hidden in [
        "HIDDEN_CANONICAL_FACT",
        "PRIVATE_CONTROLLER_RULE",
        "OPERATOR_REVISION_NOTE",
        "ABANDONED_TIMELINE_FACT",
        str(ids["branch_id"]),
        str(ids["run_id"]),
    ]:
        assert hidden not in fiction
    assert (
        minds.runtime_assignment(
            world_id=ids["world_id"],
            branch_id=ids["branch_id"],
            run_id=ids["run_id"],
            entity_id=entity,
        )
        == assignment
    )


def test_retry_rechecks_authority_and_new_advice_requires_active_run(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, path, run, user = setup_bound_character(app)
    body = {"run_id": run, "idempotency_key": "before-pause"}
    first = player.post(path + "/character-proposals", json=body)
    assert first.status_code == 200
    sim = app.extensions["simulation"]
    current = sim.runs[uuid.UUID(run)]
    sim.runs[current.run_id] = current.model_copy(update={"status": "PAUSED"})
    assert player.post(path + "/character-proposals", json=body).get_json() == first.get_json()
    assert (
        player.post(
            path + "/character-proposals", json={**body, "idempotency_key": "paused-new"}
        ).status_code
        == 400
    )
    # A role in a different world must not retain current-world proposal permission.
    other_world = admin.post(
        "/api/v2/worlds", json={"name": "Unrelated authority " + uuid.uuid4().hex}
    ).get_json()
    assert (
        admin.put(
            f"/api/v2/admin/users/{user}/worlds/{other_world['world_id']}/roles",
            json={"roles": ["DM"]},
        ).status_code
        == 200
    )
    assert (
        admin.put(
            f"/api/v2/admin/users/{user}/worlds/{card['world_id']}/roles", json={"roles": []}
        ).status_code
        == 200
    )
    assert player.post(path + "/character-proposals", json=body).status_code == 403
