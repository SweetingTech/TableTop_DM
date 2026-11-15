from __future__ import annotations

import json
import uuid

import pytest

from cognition.dialogue_generation import generate_dialogue
from cognition.models import Memory, MindState
from tests.unit.cognition.test_character_context import assemble, fixture_context

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("source", ["abandoned_branch", "foreign_world", "operator", "masked"])
def test_forbidden_sources_and_forged_memories_never_reach_generated_speech(source):
    scene, actor, event, observation, grant = fixture_context()
    payload = {"text": "The bridge is open.", "speaker_entity_id": str(uuid.UUID(int=9000))}
    good = event.model_copy(update={"payload": payload})
    seen = observation.model_copy(update={"perceived_payload": payload})
    heard = grant.model_copy(update={"allowed_payload_fields": ("text", "speaker_entity_id")})
    forbidden = good.model_copy(
        update={
            "event_id": uuid.uuid4(),
            "payload": {**payload, "text": "ABANDONED_PLOT_SECRET"},
        }
    )
    if source == "abandoned_branch":
        forbidden = forbidden.model_copy(update={"branch_id": uuid.uuid4()})
    elif source == "foreign_world":
        forbidden = forbidden.model_copy(update={"world_id": uuid.uuid4()})
    elif source == "operator":
        forbidden = forbidden.model_copy(update={"domain_tags": ("operator", "director")})
    raw = seen.model_copy(
        update={
            "observation_id": uuid.uuid4(),
            "source_event_id": forbidden.event_id,
            "perceived_payload": forbidden.payload,
        }
    )
    frozen = heard.model_copy(update={"event_id": forbidden.event_id})
    if source == "masked":
        frozen = frozen.model_copy(update={"hidden_payload_fields": frozenset({"text"})})
    forged = Memory(
        entity_id=scene.observer_entity_id,
        source_event_id=forbidden.event_id,
        source_observation_id=raw.observation_id,
        summary="ABANDONED_MEMORY_SECRET",
        emotional_weight=0,
        importance=1,
        recall_strength=1,
    )
    mind = MindState(entity_id=scene.observer_entity_id, memories=(forged,))
    context = assemble(
        scene,
        actor,
        {good.event_id: good, forbidden.event_id: forbidden},
        [seen, raw],
        {
            (good.event_id, scene.observer_entity_id): heard,
            (forbidden.event_id, scene.observer_entity_id): frozen,
        },
        mind,
    )
    encoded = json.dumps(context.situation())
    assert "ABANDONED_PLOT_SECRET" not in encoded
    assert "ABANDONED_MEMORY_SECRET" not in encoded
    assert all(m.summary != forged.summary for m in context.memories)
    requests = []

    class Provider:
        model_version = "boundary-flow-fixture"

        def complete(self, request):
            requests.append(request)
            assert "ABANDONED_" not in request.model_dump_json()
            return {
                "text": "The bridge is open.",
                "sources": [row["reference"] for row in request.experiences],
            }

    speech, receipt = generate_dialogue(
        context, {"text": "Hello.", "volume": "NORMAL"}, {}, 17, Provider()
    )
    assert len(requests) == 1 and receipt.status == "GENERATED"
    assert good.event_id in receipt.source_event_ids
    assert set(receipt.source_event_ids) <= (
        {good.event_id, forbidden.event_id} if source == "masked" else {good.event_id}
    )
    assert "ABANDONED_" not in speech
    # A scoped read filters evidence; it does not erase source memories or pretend
    # that complete campaign timeline restoration (section I) has occurred.
    assert mind.memories == (forged,)
