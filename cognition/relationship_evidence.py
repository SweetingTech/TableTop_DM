"""Fixed relationship reactions to an entity's frozen physical evidence."""

from __future__ import annotations

import uuid

from cognition.perception import PerceptionEngine, PerceptionProfile
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import NON_SENSORY_TAGS, PerceptionGrant

POLICY_VERSION = "relationship-evidence-1.0.0"


def classify_relationship(
    event: EventEnvelopeV2,
    grant: PerceptionGrant | None,
    observer: uuid.UUID,
    target: uuid.UUID,
    actor: uuid.UUID,
) -> str:
    if grant is None or not grant.modalities or NON_SENSORY_TAGS.intersection(event.domain_tags):
        raise PermissionError("relationship reaction requires physical source evidence")
    observation = PerceptionEngine().observe(
        event, PerceptionProfile(observer_entity_id=observer, observer_actor_id=actor), grant=grant
    )
    if observation is None or observation.confidence <= 0:
        raise PermissionError("relationship source was not perceived by this entity")
    facts = observation.perceived_payload
    if (
        event.event_type == "tabletop.dialogue.speak"
        and str(facts.get("speaker_entity_id")) == str(target)
        and target != observer
        and isinstance(facts.get("text"), str)
        and facts["text"].strip()
    ):
        return "conversation"
    if (
        event.event_type == "tabletop.combat.attack"
        and str(facts.get("attacker_id")) == str(target)
        and str(facts.get("target_id")) == str(observer)
        and facts.get("hit") is True
        and type(facts.get("damage")) is int
        and facts["damage"] > 0
    ):
        return "attacked"
    raise ValueError("source event has no supported relationship reaction for these entities")
