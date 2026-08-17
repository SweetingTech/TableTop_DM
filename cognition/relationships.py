from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from cognition.models import RELATIONSHIP_EVENT_DELTAS, RelationshipVector


class RelationshipModifiers(BaseModel):
    model_config = ConfigDict(frozen=True)

    forgiveness: str = "MEDIUM"
    betrayal_sensitivity: str = "MEDIUM"
    authority_trust: str = "MEDIUM"
    axis_multipliers: dict[str, float] = Field(default_factory=dict)
    event_multipliers: dict[str, float] = Field(default_factory=dict)
    attraction_permitted: bool = False


class RelationshipChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: str
    before: RelationshipVector
    requested_deltas: dict[str, float]
    applied_deltas: dict[str, float]
    after: RelationshipVector


class RelationshipChangeRecord(RelationshipChange):
    """Immutable causal evidence for one relationship projection change."""

    change_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    source_event_id: uuid.UUID
    actor_id: uuid.UUID
    policy_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @staticmethod
    def identity(
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        source_event_id: uuid.UUID,
    ) -> uuid.UUID:
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    "tabletop-dm:relationship-change",
                    str(world_id),
                    str(branch_id),
                    str(source_entity_id),
                    str(target_entity_id),
                    str(source_event_id),
                )
            ),
        )

    @classmethod
    def from_change(
        cls,
        change: RelationshipChange,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        source_event_id: uuid.UUID,
        actor_id: uuid.UUID,
        policy_version: str,
        created_at: datetime | None = None,
    ) -> RelationshipChangeRecord:
        change_id = cls.identity(
            world_id=world_id,
            branch_id=branch_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            source_event_id=source_event_id,
        )
        return cls(
            change_id=change_id,
            world_id=world_id,
            branch_id=branch_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            source_event_id=source_event_id,
            actor_id=actor_id,
            policy_version=policy_version,
            created_at=created_at or datetime.now(UTC),
            **change.model_dump(),
        )

    def immutable_content(self) -> dict:
        """Return the fields that must match when a causal retry is replayed."""

        return self.model_dump(mode="json", exclude={"created_at"})


class RelationshipEngine:
    VERSION = "relationship-policy-1.0.0"
    _BOUNDS: ClassVar[dict[str, tuple[float, float]]] = {
        "trust": (-100, 100),
        "affection": (-100, 100),
        "respect": (-100, 100),
        "fear": (0, 100),
        "resentment": (0, 100),
        "obligation": (-100, 100),
        "familiarity": (0, 100),
        "suspicion": (0, 100),
        "ideological_alignment": (-100, 100),
        "dependency": (0, 100),
        "attraction": (-100, 100),
    }
    _LEVEL: ClassVar[dict[str, float]] = {
        "LOW": 0.65,
        "MEDIUM": 1.0,
        "HIGH": 1.5,
    }

    def apply(
        self,
        vector: RelationshipVector,
        event_type: str,
        *,
        modifiers: RelationshipModifiers | None = None,
        deltas: dict[str, float] | None = None,
    ) -> RelationshipChange:
        modifiers = modifiers or RelationshipModifiers()
        if deltas is None and event_type not in RELATIONSHIP_EVENT_DELTAS:
            raise ValueError(f"Unknown relationship event type: {event_type}")
        requested = dict(
            RELATIONSHIP_EVENT_DELTAS.get(event_type, {}) if deltas is None else deltas
        )
        if not requested:
            raise ValueError("Relationship deltas cannot be empty")
        unknown = set(requested) - set(self._BOUNDS)
        if unknown:
            raise ValueError(f"Unknown relationship axes: {sorted(unknown)}")

        values = vector.model_dump()
        applied: dict[str, float] = {}
        event_multiplier = modifiers.event_multipliers.get(event_type, 1.0)
        for axis in sorted(requested):
            if axis == "attraction" and not modifiers.attraction_permitted:
                continue
            delta = float(requested[axis])
            multiplier = event_multiplier * modifiers.axis_multipliers.get(axis, 1.0)
            if delta < 0 and axis in {"trust", "affection", "respect"}:
                multiplier *= self._LEVEL.get(modifiers.betrayal_sensitivity, 1.0)
            if axis == "resentment":
                forgiveness = self._LEVEL.get(modifiers.forgiveness, 1.0)
                multiplier *= (2 - forgiveness) if delta > 0 else forgiveness
            if axis == "respect" and "authority" in event_type:
                multiplier *= self._LEVEL.get(modifiers.authority_trust, 1.0)

            effective = round(delta * multiplier, 6)
            current = values.get(axis)
            if current is None:
                current = 0.0
            lower, upper = self._BOUNDS[axis]
            updated = round(max(lower, min(upper, float(current) + effective)), 6)
            actual = round(updated - float(current), 6)
            values[axis] = updated
            applied[axis] = actual

        return RelationshipChange(
            event_type=event_type,
            before=vector,
            requested_deltas=requested,
            applied_deltas=applied,
            after=RelationshipVector.model_validate(values),
        )
