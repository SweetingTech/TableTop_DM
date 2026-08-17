from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cognition.models import Belief, Observation
from kernel.state import stable_hash


class BeliefClaim(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject_type: str = Field(min_length=1)
    subject_id: uuid.UUID | None = None
    predicate: str = Field(min_length=1)
    value: Any
    confidence: float = Field(default=1.0, ge=0, le=1)

    @property
    def key(self) -> tuple[str, str, str]:
        return self.subject_type, str(self.subject_id or ""), self.predicate


class BeliefRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    active_beliefs: tuple[Belief, ...]
    superseded_beliefs: tuple[Belief, ...] = ()


class BeliefEngine:
    """Revises subjective beliefs without treating an observation as world truth."""

    VERSION = "belief-revision-1.0.0"

    @staticmethod
    def claims_from_observation(observation: Observation) -> tuple[BeliefClaim, ...]:
        raw_claims = observation.perceived_payload.get("claims", ())
        if not isinstance(raw_claims, (list, tuple)):
            raise TypeError("Observation claims must be a list")
        return tuple(BeliefClaim.model_validate(claim) for claim in raw_claims)

    def revise(
        self,
        observation: Observation,
        claims: tuple[BeliefClaim, ...],
        existing: tuple[Belief, ...] = (),
    ) -> BeliefRevision:
        claim_keys = [claim.key for claim in claims]
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("An observation cannot assert the same belief key twice")

        active = {
            self._belief_key(belief): belief
            for belief in existing
            if belief.contradicted_by_event_id is None
        }
        superseded: list[Belief] = [
            belief for belief in existing if belief.contradicted_by_event_id is not None
        ]

        for claim in sorted(claims, key=lambda item: item.key):
            confidence = round(observation.confidence * claim.confidence, 6)
            prior = active.get(claim.key)
            if prior is not None and self._same_value(prior.value, claim.value):
                merged = round(1 - (1 - prior.confidence) * (1 - confidence), 6)
                active[claim.key] = prior.model_copy(
                    update={
                        "confidence": merged,
                        "source_observation_id": observation.observation_id,
                        "updated_at": observation.observed_at,
                    }
                )
                continue

            if prior is not None:
                superseded.append(
                    prior.model_copy(
                        update={
                            "contradicted_by_event_id": observation.source_event_id,
                            "updated_at": observation.observed_at,
                        }
                    )
                )

            belief_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                ":".join(
                    (
                        "tabletop-dm:belief",
                        self.VERSION,
                        str(observation.observer_entity_id),
                        str(observation.observation_id),
                        *claim.key,
                        stable_hash(claim.value),
                    )
                ),
            )
            active[claim.key] = Belief(
                belief_id=belief_id,
                entity_id=observation.observer_entity_id,
                subject_type=claim.subject_type,
                subject_id=claim.subject_id,
                predicate=claim.predicate,
                value=claim.value,
                confidence=confidence,
                source_observation_id=observation.observation_id,
                updated_at=observation.observed_at,
            )

        return BeliefRevision(
            active_beliefs=tuple(active[key] for key in sorted(active)),
            superseded_beliefs=tuple(sorted(superseded, key=lambda belief: str(belief.belief_id))),
        )

    @staticmethod
    def _belief_key(belief: Belief) -> tuple[str, str, str]:
        return belief.subject_type, str(belief.subject_id or ""), belief.predicate

    @staticmethod
    def _same_value(left: Any, right: Any) -> bool:
        return json.dumps(left, sort_keys=True, default=str) == json.dumps(
            right, sort_keys=True, default=str
        )
