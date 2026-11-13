from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from cognition.context import build_character_context
from cognition.engine import DecisionAction
from cognition.models import Belief, Memory, MindState, Observation
from domains.tabletop.spatial.scene import PerceivedEntity, PerceivedScene, SceneCoordinate
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import PerceptionGrant, PerceptionOutcome, SensoryModality

pytestmark = pytest.mark.unit


def fixture_context():
    world, branch, entity, actor = (uuid.uuid4() for _ in range(4))
    now = datetime(2040, 1, 1, tzinfo=UTC)
    scene = PerceivedScene(
        observer_entity_id=entity,
        world_id=world,
        branch_id=branch,
        projection_version=7,
        visible_zones=("town",),
        available_viewpoints=(entity, uuid.uuid4()),
        perceived_entities=(
            PerceivedEntity(
                entity_id=entity,
                name="Gardener",
                position=SceneCoordinate(x=1, y=2),
                position_confidence=1,
                knowledge_state="VISIBLE",
                detail_level="INSPECTED",
            ),
        ),
        recent_observations=(),
        generated_at=now,
    )
    event = EventEnvelopeV2(
        world_id=world,
        branch_id=branch,
        run_id=uuid.uuid4(),
        actor_id=actor,
        event_type="tabletop.dialogue.speak",
        visible_to=(actor,),
        correlation_id=uuid.uuid4(),
        domain_tags=("dialogue",),
        created_at=now,
        payload={
            "text": "The bridge is open.",
            "secret_state": "HIDDEN_PLOT",
            "claims": [{"subject_type": "place", "predicate": "bridge_open", "value": True}],
        },
    )
    observation = Observation(
        observer_entity_id=entity,
        source_event_id=event.event_id,
        perceived_payload=event.payload,
        confidence=0.8,
        observed_at=now,
    )
    grant = PerceptionGrant(
        event_id=event.event_id,
        world_id=world,
        branch_id=branch,
        observer_entity_id=entity,
        modalities=(SensoryModality.SOUND,),
        outcome=PerceptionOutcome.DIRECT,
        confidence=0.8,
        allowed_payload_fields=("text", "claims"),
        resolver_version="test",
        spatial_context_hash="a" * 64,
    )
    return scene, actor, event, observation, grant


def assemble(scene, actor, events, observations, grants, mind=None, **options):
    return build_character_context(
        scene=scene,
        actor_id=actor,
        mind=mind or MindState(entity_id=scene.observer_entity_id),
        observations=tuple(observations),
        event_reader=events.get,
        grant_reader=lambda event_id, entity_id: grants.get((event_id, entity_id)),
        **options,
    )


def test_context_uses_masked_same_branch_evidence_and_sanitizes_memory_overrides():
    scene, actor, event, observation, grant = fixture_context()
    good = Belief(
        entity_id=scene.observer_entity_id,
        subject_type="place",
        predicate="bridge_open",
        value=True,
        confidence=0.8,
        source_observation_id=observation.observation_id,
    )
    forged = good.model_copy(update={"belief_id": uuid.uuid4(), "value": "HIDDEN_PLOT"})
    memory = Memory(
        entity_id=scene.observer_entity_id,
        source_event_id=event.event_id,
        source_observation_id=observation.observation_id,
        summary="OPERATOR_OVERRIDE",
        emotional_weight=0,
        importance=1,
        recall_strength=1,
    )
    mind = MindState(entity_id=scene.observer_entity_id, beliefs=(good, forged), memories=(memory,))
    before = mind.model_dump(mode="json")
    context = assemble(
        scene,
        actor,
        {event.event_id: event},
        [observation],
        {(event.event_id, scene.observer_entity_id): grant},
        mind,
    )
    assert context.beliefs == (good,)
    assert context.memories[0].summary == "The bridge is open."
    situation = json.dumps(context.situation())
    assert "The bridge is open." in situation
    for forbidden in (
        "HIDDEN_PLOT",
        "OPERATOR_OVERRIDE",
        "secret_state",
        "branch_id",
        "projection_version",
        "available_viewpoints",
        "source_event_id",
    ):
        assert forbidden not in situation
    assert mind.model_dump(mode="json") == before
    assert "secret_state" in observation.perceived_payload
    changed_clock = scene.model_copy(update={"generated_at": datetime.now(UTC)})
    repeated = assemble(
        changed_clock,
        actor,
        {event.event_id: event},
        [observation],
        {(event.event_id, scene.observer_entity_id): grant},
        mind,
    )
    assert context.evidence_hash == repeated.evidence_hash


@pytest.mark.parametrize("kind", ["branch", "world", "observer", "grant", "operator", "no_grant"])
def test_context_excludes_abandoned_foreign_and_operator_evidence(kind):
    scene, actor, event, observation, grant = fixture_context()
    if kind in {"branch", "world"}:
        event = event.model_copy(update={kind + "_id": uuid.uuid4()})
    elif kind == "observer":
        observation = observation.model_copy(update={"observer_entity_id": uuid.uuid4()})
    elif kind == "grant":
        grant = grant.model_copy(update={"branch_id": uuid.uuid4()})
    elif kind == "operator":
        event = event.model_copy(update={"domain_tags": ("operator",)})
    memory = Memory(
        entity_id=scene.observer_entity_id,
        source_event_id=event.event_id,
        source_observation_id=observation.observation_id,
        summary="ABANDONED_TRUTH",
        emotional_weight=0,
        importance=1,
        recall_strength=1,
    )
    mind = MindState(entity_id=scene.observer_entity_id, memories=(memory,))
    context = assemble(
        scene,
        actor,
        {event.event_id: event},
        [observation],
        {} if kind == "no_grant" else {(event.event_id, scene.observer_entity_id): grant},
        mind,
    )
    assert not context.observations
    assert not context.memories
    assert "ABANDONED_TRUTH" not in json.dumps(context.situation())


def test_context_preserves_event_time_grant_after_observer_moves_and_uses_server_candidates():
    scene, actor, event, observation, grant = fixture_context()
    moved = scene.model_copy(update={"perceived_entities": ()})
    candidate = DecisionAction(
        action="north", command_type="tabletop.spatial.move", parameters={"dx": 0, "dy": -1}
    )
    context = assemble(
        moved,
        actor,
        {event.event_id: event},
        [observation],
        {(event.event_id, scene.observer_entity_id): grant},
        action_provider=lambda perceived: (candidate,),
    )
    assert len(context.observations) == 1
    assert context.actions == (candidate,)
    assert context.situation()["surroundings"] == []
    with pytest.raises(ValueError, match="mind does not belong"):
        assemble(scene, actor, {}, [], {}, MindState(entity_id=uuid.uuid4()))


def test_beliefs_about_distinct_subjects_retain_local_references_without_kernel_ids():
    scene, actor, event, observation, grant = fixture_context()
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    claims = [
        {
            "subject_type": "person",
            "subject_id": str(subject),
            "predicate": "location",
            "value": place,
        }
        for subject, place in ((first_id, "docks"), (second_id, "tavern"))
    ]
    payload = {"text": "Two travelers went different ways.", "claims": claims}
    event = event.model_copy(update={"payload": payload})
    observation = observation.model_copy(update={"perceived_payload": payload})
    scene = scene.model_copy(
        update={
            "perceived_entities": (
                *scene.perceived_entities,
                PerceivedEntity(
                    entity_id=first_id,
                    name="Mira",
                    position_confidence=1,
                    knowledge_state="VISIBLE",
                    detail_level="IDENTIFIED",
                ),
                PerceivedEntity(
                    entity_id=second_id,
                    name="Tomas",
                    position_confidence=1,
                    knowledge_state="VISIBLE",
                    detail_level="IDENTIFIED",
                ),
            )
        }
    )
    beliefs = tuple(
        Belief(
            entity_id=scene.observer_entity_id,
            subject_type="person",
            subject_id=subject,
            predicate="location",
            value=place,
            confidence=0.8,
            source_observation_id=observation.observation_id,
        )
        for subject, place in ((first_id, "docks"), (second_id, "tavern"))
    )
    context = assemble(
        scene,
        actor,
        {event.event_id: event},
        [observation],
        {(event.event_id, scene.observer_entity_id): grant},
        MindState(entity_id=scene.observer_entity_id, beliefs=beliefs),
    )
    situation = context.situation()
    names = {item["reference"]: item["name"] for item in situation["surroundings"]}
    assert {names[item["subject_reference"]]: item["value"] for item in situation["beliefs"]} == {
        "Mira": "docks",
        "Tomas": "tavern",
    }
    assert str(first_id) not in json.dumps(situation)
    assert str(second_id) not in json.dumps(situation)
