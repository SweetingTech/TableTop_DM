from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from kernel.contracts import CommandProposal, EventEnvelopeV2
from kernel.state import BranchState


class SensoryModality(StrEnum):
    SIGHT = "SIGHT"
    SOUND = "SOUND"
    TOUCH = "TOUCH"
    MAGIC = "MAGIC"


class PerceptionOutcome(StrEnum):
    DIRECT = "DIRECT"
    PARTIAL = "PARTIAL"


class SpatialAnchor(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID | None = None
    phase: Literal["BEFORE", "AFTER", "EXPLICIT"] = "BEFORE"
    zone_id: uuid.UUID | str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None


class EventEmission(BaseModel):
    """Deterministic sensory facts produced by a domain command."""

    model_config = ConfigDict(frozen=True)

    anchor: SpatialAnchor
    modalities: tuple[SensoryModality, ...]
    intensity: float = Field(default=1.0, ge=0)
    max_range: float = Field(default=8.0, ge=0)
    allowed_payload_fields: tuple[str, ...] | None = None
    hidden_payload_fields: frozenset[str] = frozenset()
    payload_overrides: dict[str, Any] = Field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()


class PerceptionGrant(BaseModel):
    """Frozen entity-level physical perception of one canonical event."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    observer_entity_id: uuid.UUID
    controller_actor_id: uuid.UUID | None = None
    modalities: tuple[SensoryModality, ...]
    outcome: PerceptionOutcome
    confidence: float = Field(ge=0, le=1)
    allowed_payload_fields: tuple[str, ...] | None = None
    hidden_payload_fields: frozenset[str] = frozenset()
    payload_overrides: dict[str, Any] = Field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    resolver_version: str
    spatial_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class AudienceResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    perceptions: tuple[PerceptionGrant, ...] = ()

    @property
    def controller_actor_summary(self) -> tuple[uuid.UUID, ...]:
        return tuple(
            sorted(
                {
                    grant.controller_actor_id
                    for grant in self.perceptions
                    if grant.controller_actor_id is not None
                },
                key=str,
            )
        )


class EventMaterialization(BaseModel):
    model_config = ConfigDict(frozen=True)

    event: EventEnvelopeV2
    perceptions: tuple[PerceptionGrant, ...] = ()


class SpatialPerceptionResolver(Protocol):
    def resolve(
        self,
        *,
        event_id: uuid.UUID,
        proposal: CommandProposal,
        emission: EventEmission | None,
        before: BranchState,
        after: BranchState,
    ) -> AudienceResolution: ...


class NullSpatialPerceptionResolver:
    def resolve(
        self,
        *,
        event_id: uuid.UUID,
        proposal: CommandProposal,
        emission: EventEmission | None,
        before: BranchState,
        after: BranchState,
    ) -> AudienceResolution:
        del event_id, proposal, emission, before, after
        return AudienceResolution()
