from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

import pytest

from cognition.engine import SubjectiveStatePipeline
from cognition.memory import MemoryEngine
from cognition.perception import PerceptionEngine, PerceptionProfile
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import PerceptionGrant

pytestmark = pytest.mark.unit


def _event(
    event_id: uuid.UUID,
    actor_id: uuid.UUID,
    visible_to: tuple[uuid.UUID, ...],
    value: str,
) -> EventEnvelopeV2:
    return EventEnvelopeV2(
        event_id=event_id,
        world_id=uuid.UUID(int=1),
        branch_id=uuid.UUID(int=2),
        run_id=uuid.UUID(int=3),
        actor_id=actor_id,
        event_type="world.door_observed",
        payload={
            "claims": [
                {
                    "subject_type": "door",
                    "predicate": "state",
                    "value": value,
                    "confidence": 0.9,
                }
            ],
            "public_detail": "The iron door is visible.",
            "secret_mechanism": "arcane latch",
        },
        visible_to=visible_to,
        observed_by=visible_to,
        correlation_id=uuid.UUID(int=4),
        created_at=datetime(2042, 1, 2, 3, 4, tzinfo=UTC),
    )


def _grant(event: EventEnvelopeV2, entity_id: uuid.UUID, confidence: float = 1.0):
    return PerceptionGrant(
        event_id=event.event_id,
        world_id=event.world_id,
        branch_id=event.branch_id,
        observer_entity_id=entity_id,
        modalities=("SIGHT",),
        outcome="DIRECT",
        confidence=confidence,
        resolver_version="test-resolver-1.0.0",
        spatial_context_hash="0" * 64,
    )


def test_perception_is_visibility_scoped_redacted_and_deterministic():
    source_actor = uuid.UUID(int=10)
    observer_actor = uuid.UUID(int=11)
    observer_entity = uuid.UUID(int=13)
    event = _event(uuid.UUID(int=14), source_actor, (observer_actor,), "LOCKED")
    canonical_payload = copy.deepcopy(event.payload)
    profile = PerceptionProfile(
        observer_entity_id=observer_entity,
        observer_actor_id=observer_actor,
        acuity=0.8,
        hidden_payload_fields=frozenset({"secret_mechanism"}),
    )

    grant = _grant(event, observer_entity)
    first = PerceptionEngine().observe(event, profile, grant=grant)
    second = PerceptionEngine().observe(event, profile, grant=grant)

    assert first == second
    assert first is not None
    assert first.confidence == 0.8
    assert "secret_mechanism" not in first.perceived_payload
    assert event.payload == canonical_payload
    assert (
        PerceptionEngine().observe(
            event,
            profile.model_copy(update={"observer_entity_id": uuid.UUID(int=99)}),
            grant=grant,
        )
        is None
    )
    visible_but_not_observed = event.model_copy(update={"observed_by": (source_actor,)})
    assert PerceptionEngine().observe(visible_but_not_observed, profile, grant=grant) is not None


def test_same_event_can_form_different_beliefs_then_correct_one_actor():
    source_actor = uuid.UUID(int=20)
    actor_a, actor_b = uuid.UUID(int=21), uuid.UUID(int=22)
    entity_a, entity_b = uuid.UUID(int=23), uuid.UUID(int=24)
    event = _event(uuid.UUID(int=25), source_actor, (actor_a, actor_b), "LOCKED")
    pipeline = SubjectiveStatePipeline()

    mistaken = pipeline.process(
        event,
        PerceptionProfile(
            observer_entity_id=entity_a,
            observer_actor_id=actor_a,
            acuity=0.7,
            payload_overrides={
                "claims": [
                    {
                        "subject_type": "door",
                        "predicate": "state",
                        "value": "OPEN",
                        "confidence": 0.8,
                    }
                ]
            },
        ),
        grant=_grant(event, entity_a, 0.7),
        importance=0.8,
    )
    accurate = pipeline.process(
        event,
        PerceptionProfile(
            observer_entity_id=entity_b,
            observer_actor_id=actor_b,
        ),
        grant=_grant(event, entity_b),
    )

    assert mistaken.belief_revision is not None
    assert accurate.belief_revision is not None
    assert mistaken.belief_revision.active_beliefs[0].value == "OPEN"
    assert accurate.belief_revision.active_beliefs[0].value == "LOCKED"

    correction_event = _event(uuid.UUID(int=26), source_actor, (actor_a,), "LOCKED")
    corrected = pipeline.process(
        correction_event,
        PerceptionProfile(
            observer_entity_id=entity_a,
            observer_actor_id=actor_a,
        ),
        grant=_grant(correction_event, entity_a),
        existing_beliefs=mistaken.belief_revision.active_beliefs,
    )
    assert corrected.belief_revision is not None
    assert corrected.belief_revision.active_beliefs[0].value == "LOCKED"
    assert len(corrected.belief_revision.superseded_beliefs) == 1
    assert (
        corrected.belief_revision.superseded_beliefs[0].contradicted_by_event_id
        == correction_event.event_id
    )
    assert corrected.memory is not None
    assert corrected.memory.source_event_id == correction_event.event_id


def test_memory_recall_and_decay_are_ranked_and_non_mutating():
    actor = uuid.UUID(int=30)
    entity = uuid.UUID(int=31)
    pipeline = SubjectiveStatePipeline()
    first = pipeline.process(
        _event(uuid.UUID(int=32), uuid.UUID(int=33), (actor,), "LOCKED"),
        PerceptionProfile(observer_entity_id=entity, observer_actor_id=actor),
        grant=_grant(_event(uuid.UUID(int=32), uuid.UUID(int=33), (actor,), "LOCKED"), entity),
        memory_summary="The iron door was locked by an arcane latch",
        importance=0.9,
        emotional_weight=0.4,
    ).memory
    second = pipeline.process(
        _event(uuid.UUID(int=34), uuid.UUID(int=33), (actor,), "OPEN"),
        PerceptionProfile(observer_entity_id=entity, observer_actor_id=actor),
        grant=_grant(_event(uuid.UUID(int=34), uuid.UUID(int=33), (actor,), "OPEN"), entity),
        memory_summary="A merchant sold a blue scarf",
        importance=0.3,
    ).memory
    assert first is not None and second is not None
    original_strength = first.recall_strength

    recalled = MemoryEngine.recall((second, first), "arcane locked door", limit=1)
    decayed = MemoryEngine.decay((first, second), elapsed_steps=10, decay_rate=0.05)

    assert recalled[0].memory.memory_id == first.memory_id
    assert decayed[0].recall_strength < original_strength
    assert first.recall_strength == original_strength
