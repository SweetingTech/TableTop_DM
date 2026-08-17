from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActorKind(StrEnum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class BranchKind(StrEnum):
    CANONICAL = "CANONICAL"
    TRIAL = "TRIAL"


class RunKind(StrEnum):
    LIVE = "LIVE"
    POPULATION = "POPULATION"
    EVALUATION = "EVALUATION"


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    kind: ActorKind
    display_name: str = Field(min_length=1, max_length=160)
    roles: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()
    controlled_entity_ids: frozenset[uuid.UUID] = frozenset()

    def has_capabilities(self, required: frozenset[str]) -> bool:
        return required.issubset(self.capabilities)


class CommandProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    command_type: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    interaction_id: uuid.UUID | None = None
    actor_id: uuid.UUID
    embodied_entity_id: uuid.UUID | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=200)
    correlation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    causation_id: uuid.UUID | None = None
    seed: int | None = None
    decision_trace_id: uuid.UUID | None = None
    persona_version: str | None = None
    policy_version: str | None = None
    prompt_contract_version: str | None = None
    model_version: str | None = None


class StateDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    projection: str
    operation: Literal["SET", "MERGE", "DELETE", "INCREMENT"]
    entity_id: uuid.UUID | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class EntityMutation(BaseModel):
    """Typed metadata mutation committed beside projection deltas."""

    model_config = ConfigDict(frozen=True)

    operation: Literal["CREATE"] = "CREATE"
    entity_id: uuid.UUID
    entity_type: str
    name: str
    public_state: dict[str, Any] = Field(default_factory=dict)
    secret_state: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)
    controller_actor_id: uuid.UUID | None = None


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    deltas: tuple[StateDelta, ...] = ()
    # Internal unit-of-work instructions are deliberately omitted from public
    # receipts and ledger result JSON; projections/events expose only public
    # command facts while the transaction persists private entity metadata.
    entity_mutations: tuple[EntityMutation, ...] = Field(default=(), exclude=True, repr=False)
    domain_tags: tuple[str, ...] = ()


class DecisionCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str
    score: float
    factors: dict[str, float]


class DecisionTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    persona_id: uuid.UUID
    persona_version: str
    policy_version: str
    runtime_kind: str
    seed: int
    candidates: tuple[DecisionCandidate, ...]
    chosen_action: str
    decision_tier: Literal["REFLEX", "UTILITY", "PLANNER", "LLM"] | None = None
    rationale: str | None = None
    fallback_reason: str | None = None
    plan: tuple[str, ...] = ()
    prompt_contract_version: str | None = None
    model_version: str | None = None


class EventEnvelopeV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_version: int = Field(default=2, ge=2)
    contract_version: str = "2.0.0"
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    interaction_id: uuid.UUID | None = None
    actor_id: uuid.UUID
    embodied_entity_id: uuid.UUID | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    observed_by: tuple[uuid.UUID, ...] = ()
    visible_to: tuple[uuid.UUID, ...]
    parent_event_id: uuid.UUID | None = None
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None = None
    domain_tags: tuple[str, ...] = ()
    idempotency_key: str | None = None
    persona_version: str | None = None
    policy_version: str | None = None
    prompt_contract_version: str | None = None
    model_version: str | None = None
    seed: int | None = None
    decision_trace_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("visible_to")
    @classmethod
    def visible_to_cannot_be_empty(cls, value: tuple[uuid.UUID, ...]) -> tuple[uuid.UUID, ...]:
        if not value:
            raise ValueError("visible_to must contain at least one actor")
        return value


class VerifierFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    fact_type: str
    value: bool | int | float | str
    unit: str | None = None
    evidence_event_ids: tuple[uuid.UUID, ...] = ()
    verifier_version: str
