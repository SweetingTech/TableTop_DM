from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from cognition.context import CharacterContext
from cognition.conversation import due_reply
from cognition.dialogue_generation import generate_dialogue
from cognition.models import Observation
from domains.tabletop.spatial.scene import PerceivedScene
from kernel.contracts import EventEnvelopeV2
from kernel.control import ControllerState

pytestmark = pytest.mark.unit


@pytest.fixture
def conversation():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    control = ControllerState(
        world_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        entity_id=uuid.uuid4(),
        owner_actor_id=uuid.uuid4(),
        executor_actor_id=uuid.uuid4(),
        epoch=1,
        mode="AUTONOMOUS",
        next_due=now,
    )
    scene = PerceivedScene(
        observer_entity_id=control.entity_id,
        world_id=control.world_id,
        branch_id=control.branch_id,
        projection_version=1,
        visible_zones=("world",),
        perceived_entities=(),
        recent_observations=(),
        available_viewpoints=(),
    )
    sender = uuid.uuid4()
    event = EventEnvelopeV2(
        world_id=control.world_id,
        branch_id=control.branch_id,
        run_id=control.run_id,
        actor_id=uuid.uuid4(),
        embodied_entity_id=sender,
        event_type="tabletop.dialogue.speak",
        domain_tags=("tabletop", "speech"),
        visible_to=(uuid.uuid4(),),
        correlation_id=uuid.uuid4(),
        created_at=now - timedelta(seconds=2),
    )
    observation = Observation(
        observer_entity_id=control.entity_id,
        source_event_id=event.event_id,
        perceived_payload={
            "speaker_entity_id": str(sender),
            "text": "When does the ferry leave?",
            "language": "common",
        },
        confidence=1,
        observed_at=now - timedelta(seconds=1),
    )
    context = CharacterContext(scene=scene, observations=(observation,), memories=(), beliefs=())
    return now, control, context, event


def test_reply_follows_due_time_and_scoped_masked_observation(conversation):
    now, control, context, source = conversation
    events = {source.event_id: source}
    planned = due_reply(context, control, events.get, now=now)
    assert planned is not None and planned.due_at == now
    assert planned.source_event_id == source.event_id
    assert planned.source_observation_id == context.observations[0].observation_id
    assert planned.correlation_id == source.correlation_id and planned.source_language == "common"
    assert due_reply(context, control, events.get, now=now - timedelta(milliseconds=1)) is None

    for update in ({"run_id": uuid.uuid4()}, {"domain_tags": ("director",)}):
        rejected = source.model_copy(update=update)
        assert due_reply(context, control, {source.event_id: rejected}.get, now=now) is None
    unobserved = context.model_copy(update={"observations": ()})
    assert due_reply(unobserved, control, events.get, now=now) is None

    own = source.model_copy(
        update={"event_id": uuid.uuid4(), "embodied_entity_id": control.entity_id}
    )
    heard = context.observations[0].model_copy(
        update={
            "source_event_id": own.event_id,
            "perceived_payload": {"text": "At dawn.", "speaker_entity_id": str(control.entity_id)},
        }
    )
    already_replied = context.model_copy(update={"observations": (*context.observations, heard)})
    assert due_reply(already_replied, control, {**events, own.event_id: own}.get, now=now) is None


def test_provider_grounds_reply_in_exact_scheduled_speech(conversation):
    _, _, context, source = conversation
    distracting_speech = tuple(
        context.observations[0].model_copy(
            update={
                "source_event_id": uuid.uuid4(),
                "perceived_payload": {"text": "The wind shifted.", "speaker_entity_id": "someone"},
            }
        )
        for _ in range(13)
    )
    context = context.model_copy(
        update={"observations": (*context.observations, *distracting_speech)}
    )
    seen = []

    class Grounded:
        model_version = "reply-model-fixture"

        def complete(self, request):
            seen.append(request)
            prompt = next(
                row for row in request.experiences if row["reference"] == request.reply_to
            )
            assert prompt["text"] == "When does the ferry leave?"
            return {"text": "At dawn, if the harbor stays calm.", "sources": [request.reply_to]}

    line, receipt = generate_dialogue(
        context,
        {"text": "Hello.", "language": "common", "volume": "WHISPER"},
        {},
        42,
        Grounded(),
        reply_event_id=source.event_id,
    )
    assert line == "At dawn, if the harbor stays calm." and receipt.status == "GENERATED"
    assert receipt.source_event_ids == (source.event_id,)
    assert seen[0].language == "common" and seen[0].volume == "WHISPER"
    assert str(source.event_id) not in seen[0].model_dump_json()
