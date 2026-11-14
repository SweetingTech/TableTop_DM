from __future__ import annotations

import copy
import uuid
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, ValidationError

from cognition.beliefs import BeliefClaim
from cognition.engine import DecisionAction
from cognition.models import Belief, Memory, MindState, Observation
from cognition.perception import PerceptionEngine, PerceptionProfile
from domains.tabletop.character_history import CharacterCardContent
from domains.tabletop.spatial.scene import PerceivedScene
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import PerceptionGrant
from kernel.state import stable_hash

EventReader = Callable[[uuid.UUID], EventEnvelopeV2 | None]
GrantReader = Callable[[uuid.UUID, uuid.UUID], PerceptionGrant | None]
ActionProvider = Callable[[PerceivedScene], tuple[DecisionAction, ...]]
NON_SENSORY_TAGS = frozenset(
    {"operator", "director", "timeline_revision", "checkpoint", "protection_policy", "evaluation"}
)


def validated_observations(
    observations: tuple[Observation, ...],
    *,
    world_id: uuid.UUID,
    branch_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_id: uuid.UUID,
    event_reader: EventReader,
    grant_reader: GrantReader,
) -> tuple[Observation, ...]:
    """Validate recorded experience against its frozen grant, never the current audience."""
    profile = PerceptionProfile(observer_entity_id=entity_id, observer_actor_id=actor_id)
    result: dict[uuid.UUID, Observation] = {}
    for observation in observations:
        if observation.observer_entity_id != entity_id:
            continue
        event = event_reader(observation.source_event_id)
        grant = grant_reader(observation.source_event_id, entity_id)
        if (
            event is None
            or grant is None
            or not grant.modalities
            or (event.world_id, event.branch_id) != (world_id, branch_id)
            or NON_SENSORY_TAGS.intersection(event.domain_tags)
        ):
            continue
        masked = PerceptionEngine().observe(event, profile, grant=grant)
        if masked is None:
            continue
        # A stored summary/override is not authority to add facts to physical evidence.
        # Keep any narrower recorded mask; do not reveal additional grant-allowed fields.
        payload = {
            key: copy.deepcopy(value)
            for key, value in observation.perceived_payload.items()
            if key in masked.perceived_payload and value == masked.perceived_payload[key]
        }
        result[observation.observation_id] = observation.model_copy(
            update={
                "perceived_payload": payload,
                "confidence": min(observation.confidence, grant.confidence),
                "observed_at": event.created_at,
            }
        )
    return tuple(
        sorted(result.values(), key=lambda item: (item.observed_at, str(item.observation_id)))
    )


def experience_summary(observation: Observation) -> str:
    payload = observation.perceived_payload
    for key in ("summary", "text"):
        if isinstance(payload.get(key), str):
            return str(payload[key])
    destination = payload.get("destination")
    if isinstance(destination, dict) and "x" in destination and "y" in destination:
        return f"Movement to ({destination['x']}, {destination['y']})."
    return "An event was perceived."


class CharacterContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    context_version: str = "character-context-1.1.2"
    scene: PerceivedScene
    observations: tuple[Observation, ...]
    beliefs: tuple[Belief, ...]
    memories: tuple[Memory, ...]
    actions: tuple[DecisionAction, ...] = ()
    identity: CharacterCardContent | None = None

    @property
    def evidence_hash(self) -> str:
        payload = self.model_dump(mode="json")
        payload["scene"].pop("generated_at")
        payload["scene"].pop("available_viewpoints")
        return stable_hash(payload)

    def situation(self) -> dict:
        """Model-facing fiction, excluding controller, ledger, version, and timeline metadata."""
        observer = self.scene.observer_entity_id
        subjects = {entity.entity_id for entity in self.scene.perceived_entities}
        subjects.update(
            belief.subject_id for belief in self.beliefs if belief.subject_id is not None
        )
        references = {observer: "self"}
        references.update(
            {
                subject: f"subject-{index}"
                for index, subject in enumerate(sorted(subjects - {observer}, key=str), 1)
            }
        )
        return {
            "identity": {
                "name": self.identity.name,
                "species": self.identity.species,
                "class_name": self.identity.class_name,
                "background": self.identity.background,
                **self.identity.authored_identity.model_dump(
                    mode="json", exclude={"initial_known_facts"}
                ),
                "starting_knowledge_claims": list(
                    self.identity.authored_identity.initial_known_facts
                ),
            }
            if self.identity
            else None,
            "surroundings": [
                {
                    "reference": references[entity.entity_id],
                    **entity.model_dump(
                        mode="json",
                        exclude_none=True,
                        exclude={
                            "entity_id",
                            "observed_at",
                            "knowledge_state",
                            "detail_level",
                            "position_confidence",
                        },
                    ),
                }
                for entity in self.scene.perceived_entities
            ],
            "experiences": [experience_summary(item) for item in self.observations],
            "beliefs": [
                {
                    "subject_reference": references.get(belief.subject_id, belief.subject_type)
                    if belief.subject_id
                    else "self"
                    if belief.subject_type == "self"
                    else belief.subject_type,
                    **belief.model_dump(
                        mode="json",
                        include={
                            "subject_type",
                            "predicate",
                            "value",
                            "confidence",
                        },
                    ),
                }
                for belief in self.beliefs
            ],
            "memories": [memory.summary for memory in self.memories],
        }


def build_character_context(
    *,
    scene: PerceivedScene,
    mind: MindState,
    observations: tuple[Observation, ...],
    actor_id: uuid.UUID,
    event_reader: EventReader,
    grant_reader: GrantReader,
    action_provider: ActionProvider | None = None,
    identity: CharacterCardContent | None = None,
    event_order: dict[uuid.UUID, int] | None = None,
) -> CharacterContext:
    """Read-only context assembly; all readers/providers are trusted server dependencies."""
    entity_id = scene.observer_entity_id
    if mind.entity_id != entity_id:
        raise ValueError("mind does not belong to the scene observer")
    eligible = validated_observations(
        observations,
        world_id=scene.world_id,
        branch_id=scene.branch_id,
        entity_id=entity_id,
        actor_id=actor_id,
        event_reader=event_reader,
        grant_reader=grant_reader,
    )
    if event_order is not None:
        eligible = tuple(sorted(eligible, key=lambda row: event_order[row.source_event_id]))
    by_id = {item.observation_id: item for item in eligible}
    beliefs: list[Belief] = []
    for belief in mind.beliefs:
        source = by_id.get(belief.source_observation_id) if belief.source_observation_id else None
        if source is None or belief.entity_id != entity_id or belief.contradicted_by_event_id:
            continue
        try:
            claims = tuple(
                BeliefClaim.model_validate(claim)
                for claim in source.perceived_payload.get("claims", ())
            )
        except (ValidationError, TypeError):
            continue
        if any(
            (claim.subject_type, claim.subject_id, claim.predicate, stable_hash(claim.value))
            == (belief.subject_type, belief.subject_id, belief.predicate, stable_hash(belief.value))
            for claim in claims
        ):
            beliefs.append(belief.model_copy(deep=True))
    memories: list[Memory] = []
    for memory in sorted(mind.memories, key=lambda item: (item.created_at, str(item.memory_id))):
        source = by_id.get(memory.source_observation_id) if memory.source_observation_id else None
        if (
            source is not None
            and memory.entity_id == entity_id
            and memory.source_event_id == source.source_event_id
        ):
            memories.append(
                memory.model_copy(update={"summary": experience_summary(source)}, deep=True)
            )
    return CharacterContext(
        identity=identity.model_copy(deep=True) if identity is not None else None,
        scene=scene.model_copy(deep=True),
        observations=eligible[-80:],
        beliefs=tuple(sorted(beliefs, key=lambda item: str(item.belief_id))),
        memories=tuple(memories[-80:]),
        actions=tuple(action.model_copy(deep=True) for action in action_provider(scene))
        if action_provider is not None
        else (),
    )
