from __future__ import annotations

import copy
import uuid
from datetime import timedelta

import pytest

from cognition.context import CharacterContextPending, require_projected_experience
from cognition.perception import PerceptionEngine, PerceptionProfile
from tests.unit.cognition.test_character_context import fixture_context

pytestmark = pytest.mark.unit


def _recorded():
    scene, actor, event, _, grant = fixture_context()
    original = grant.model_copy(update={"confidence": 0.916667})
    profile = PerceptionProfile(
        observer_entity_id=scene.observer_entity_id, observer_actor_id=actor
    )
    observation = PerceptionEngine().observe(event, profile, grant=original)
    assert observation is not None
    stored = observation.model_copy(update={"confidence": 0.9167})
    rounded = original.model_copy(update={"confidence": 0.9167})
    expected = PerceptionEngine().observe(event, profile, grant=rounded)
    assert expected is not None and expected.observation_id != stored.observation_id
    return {
        "world_id": scene.world_id,
        "branch_id": scene.branch_id,
        "entity_id": scene.observer_entity_id,
        "actor_id": actor,
        "grants": (rounded,),
        "event_reader": {event.event_id: event}.get,
        "observation_exists": lambda identifier: identifier == stored.observation_id,
    }, stored


def test_complete_stored_precision_observation_satisfies_durable_gate_without_rewriting_ids():
    arguments, stored = _recorded()
    with pytest.raises(CharacterContextPending):
        require_projected_experience(**arguments, recorded_observations=(stored,))
    require_projected_experience(
        **arguments, recorded_observations=(stored,), stored_confidence_precision=True
    )


def test_precision_compatibility_distinguishes_boolean_from_integer_payload():
    arguments, stored = _recorded()
    altered_payload = copy.deepcopy(stored.perceived_payload)
    altered_payload["claims"][0]["value"] = 1
    assert altered_payload == stored.perceived_payload
    altered = stored.model_copy(update={"perceived_payload": altered_payload})
    with pytest.raises(CharacterContextPending):
        require_projected_experience(
            **arguments, recorded_observations=(altered,), stored_confidence_precision=True
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"perceived_payload": {"text": "Invented hidden evidence"}},
        {"confidence": 0.99},
        {"source_event_id": uuid.uuid4()},
        {"observer_entity_id": uuid.uuid4()},
        {"observed_at": None},
    ],
)
def test_precision_compatibility_rejects_different_source_body_mask_time_or_confidence(changed):
    arguments, stored = _recorded()
    if changed.get("observed_at", False) is None:
        changed = {"observed_at": stored.observed_at + timedelta(seconds=1)}
    altered = stored.model_copy(update=changed)
    with pytest.raises(CharacterContextPending):
        require_projected_experience(
            **arguments, recorded_observations=(altered,), stored_confidence_precision=True
        )
