from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

RuntimeKind: TypeAlias = Literal[
    "DETERMINISTIC",
    "UTILITY",
    "PLANNER",
    "LOCAL_LLM",
    "HOSTED_LLM",
    "HUMAN",
    "REPLAY",
]

EvidenceType: TypeAlias = Literal[
    "DIRECT_OBSERVATION",
    "TESTIMONY",
    "DOCUMENT",
    "INFERENCE",
    "MAGIC",
]


class RuntimeAssignment(BaseModel):
    """Versionable controller selection, independent from persona and embodiment."""

    model_config = ConfigDict(frozen=True)

    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    runtime_kind: RuntimeKind
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    observer_entity_id: uuid.UUID
    source_event_id: uuid.UUID
    perceived_payload: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Belief(BaseModel):
    model_config = ConfigDict(frozen=True)

    belief_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    entity_id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID | None = None
    predicate: str
    value: Any
    confidence: float = Field(ge=0, le=1)
    source_observation_id: uuid.UUID | None = None
    contradicted_by_event_id: uuid.UUID | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Memory(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    entity_id: uuid.UUID
    source_event_id: uuid.UUID
    source_observation_id: uuid.UUID | None = None
    summary: str
    emotional_weight: float = Field(ge=-1, le=1)
    importance: float = Field(ge=0, le=1)
    recall_strength: float = Field(ge=0, le=1)
    visibility: str = "PRIVATE"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BeliefEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    entity_id: uuid.UUID
    belief_id: uuid.UUID | None = None
    source_observation_id: uuid.UUID
    evidence_type: EvidenceType
    immediate_source_entity_id: uuid.UUID | None = None
    claimed_origin_event_id: uuid.UUID | None = None
    parent_evidence_id: uuid.UUID | None = None
    direct_witness: bool
    confidence_modifier: float = Field(default=1.0, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ObservationDisposition(BaseModel):
    model_config = ConfigDict(frozen=True)

    persist_observation: bool = True
    revise_beliefs: bool = True
    create_memory: bool = False
    importance: float = Field(default=0.0, ge=0, le=1)
    emotional_weight: float = Field(default=0.0, ge=-1, le=1)


class RelationshipVector(BaseModel):
    model_config = ConfigDict(frozen=True)

    trust: float = Field(default=0, ge=-100, le=100)
    affection: float = Field(default=0, ge=-100, le=100)
    respect: float = Field(default=0, ge=-100, le=100)
    fear: float = Field(default=0, ge=0, le=100)
    resentment: float = Field(default=0, ge=0, le=100)
    obligation: float = Field(default=0, ge=-100, le=100)
    familiarity: float = Field(default=0, ge=0, le=100)
    suspicion: float = Field(default=0, ge=0, le=100)
    ideological_alignment: float = Field(default=0, ge=-100, le=100)
    dependency: float = Field(default=0, ge=0, le=100)
    attraction: float | None = Field(default=None, ge=-100, le=100)


class MindState(BaseModel):
    entity_id: uuid.UUID
    mood: str = "NEUTRAL"
    stress: float = Field(default=0, ge=0, le=100)
    attention_budget: float = Field(default=100, ge=0, le=100)
    active_plan: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    needs: dict[str, float] = Field(default_factory=dict)
    beliefs: tuple[Belief, ...] = ()
    memories: tuple[Memory, ...] = ()


RELATIONSHIP_EVENT_DELTAS: dict[str, dict[str, float]] = {
    "kept_promise": {"trust": 12, "respect": 4, "obligation": -2},
    "public_humiliation": {"affection": -8, "respect": -6, "resentment": 15, "fear": 2},
    "saved_life": {"trust": 20, "affection": 10, "obligation": 25},
}
