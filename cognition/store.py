from __future__ import annotations

import threading
import uuid

from cognition.beliefs import BeliefRevision
from cognition.engine import DecisionOutcome, SubjectiveUpdate
from cognition.models import (
    Belief,
    MindState,
    Observation,
    RelationshipVector,
    RuntimeAssignment,
)
from cognition.relationships import RelationshipChangeRecord


class MindStore:
    """Reference subjective projection; canonical world truth remains elsewhere."""

    def __init__(self) -> None:
        self._states: dict[tuple[uuid.UUID | None, uuid.UUID], MindState] = {}
        self._observations: dict[tuple[uuid.UUID | None, uuid.UUID], Observation] = {}
        self._relationships: dict[
            tuple[uuid.UUID | None, uuid.UUID, uuid.UUID], RelationshipVector
        ] = {}
        self._relationship_changes: dict[tuple[uuid.UUID, uuid.UUID], RelationshipChangeRecord] = {}
        self._runtime_assignments: dict[
            tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID], RuntimeAssignment
        ] = {}
        self._decisions: dict[uuid.UUID, DecisionOutcome] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(
        entity_id: uuid.UUID, branch_id: uuid.UUID | None
    ) -> tuple[uuid.UUID | None, uuid.UUID]:
        return branch_id, entity_id

    def initialize(self, state: MindState, *, branch_id: uuid.UUID | None = None) -> MindState:
        with self._lock:
            existing = self._states.setdefault(self._key(state.entity_id, branch_id), state)
            if existing != state:
                raise ValueError("mind state is already initialized")
            return existing

    def restore(
        self,
        state: MindState,
        *,
        branch_id: uuid.UUID,
        observations: tuple[Observation, ...] = (),
        relationships: tuple[tuple[uuid.UUID, RelationshipVector], ...] = (),
    ) -> MindState:
        """Restore a durable branch-scoped projection during process startup."""
        with self._lock:
            self._states[self._key(state.entity_id, branch_id)] = state
            for observation in observations:
                if observation.observer_entity_id != state.entity_id:
                    raise ValueError("observation belongs to another entity")
                self._observations[(branch_id, observation.observation_id)] = observation
            for target_entity_id, vector in relationships:
                self._relationships[(branch_id, state.entity_id, target_entity_id)] = vector
            return state

    def get(self, entity_id: uuid.UUID, *, branch_id: uuid.UUID | None = None) -> MindState:
        """Return the current immutable subjective projection."""
        with self._lock:
            return self._states.get(self._key(entity_id, branch_id), MindState(entity_id=entity_id))

    def relationship(
        self,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        *,
        branch_id: uuid.UUID | None = None,
    ) -> RelationshipVector:
        with self._lock:
            return self._relationships.get(
                (branch_id, source_entity_id, target_entity_id), RelationshipVector()
            )

    def apply_subjective_update(
        self,
        entity_id: uuid.UUID,
        update: SubjectiveUpdate,
        *,
        branch_id: uuid.UUID | None = None,
    ) -> MindState:
        with self._lock:
            key = self._key(entity_id, branch_id)
            self._states.setdefault(key, MindState(entity_id=entity_id))
            if update.observation is not None:
                if update.observation.observer_entity_id != entity_id:
                    raise ValueError("observation belongs to another entity")
                self._observations.setdefault(
                    (branch_id, update.observation.observation_id), update.observation
                )
            committed = self.preview_subjective_update(entity_id, update, branch_id=branch_id)
            self._states[key] = committed
            return committed

    def preview_subjective_update(
        self,
        entity_id: uuid.UUID,
        update: SubjectiveUpdate,
        *,
        branch_id: uuid.UUID | None = None,
    ) -> MindState:
        """Project an update without storing it, for durable commit-before-publish flows."""
        with self._lock:
            state = self._states.get(
                self._key(entity_id, branch_id), MindState(entity_id=entity_id)
            )
            beliefs = list(state.beliefs)
            if update.belief_revision is not None:
                beliefs = self._apply_belief_revision(beliefs, update.belief_revision)
            memories = list(state.memories)
            if update.memory is not None and all(
                item.memory_id != update.memory.memory_id for item in memories
            ):
                memories.append(update.memory)
            return state.model_copy(update={"beliefs": tuple(beliefs), "memories": tuple(memories)})

    @staticmethod
    def _apply_belief_revision(existing: list[Belief], revision: BeliefRevision) -> list[Belief]:
        # A revision is a complete projection: active beliefs plus the immutable
        # contradicted history.  Replacing from that projection avoids retaining a
        # stale active copy of a belief that was superseded by this observation.
        projected = {
            item.belief_id: item
            for item in (*revision.active_beliefs, *revision.superseded_beliefs)
        }
        return [projected[key] for key in sorted(projected, key=str)]

    def set_relationship(
        self,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
        vector: RelationshipVector,
        *,
        branch_id: uuid.UUID | None = None,
    ) -> RelationshipVector:
        if source_entity_id == target_entity_id:
            raise ValueError("self relationships are not supported")
        with self._lock:
            self._relationships[(branch_id, source_entity_id, target_entity_id)] = vector
            return vector

    def apply_relationship_change(
        self, record: RelationshipChangeRecord
    ) -> RelationshipChangeRecord:
        """Atomically publish one causal relationship change, idempotently."""

        history_key = (record.branch_id, record.change_id)
        relationship_key = (
            record.branch_id,
            record.source_entity_id,
            record.target_entity_id,
        )
        with self._lock:
            existing = self._relationship_changes.get(history_key)
            if existing is not None:
                if existing.immutable_content() != record.immutable_content():
                    raise ValueError("relationship change retry differs from immutable history")
                return existing
            current = self._relationships.get(relationship_key, RelationshipVector())
            if current != record.before and current != record.after:
                raise ValueError("relationship projection changed before causal update")
            self._relationship_changes[history_key] = record
            self._relationships[relationship_key] = record.after
            return record

    def relationship_change(
        self, change_id: uuid.UUID, *, branch_id: uuid.UUID
    ) -> RelationshipChangeRecord | None:
        with self._lock:
            return self._relationship_changes.get((branch_id, change_id))

    def set_runtime_assignment(self, assignment: RuntimeAssignment) -> RuntimeAssignment:
        key = (
            assignment.world_id,
            assignment.branch_id,
            assignment.run_id,
            assignment.entity_id,
        )
        with self._lock:
            self._runtime_assignments[key] = assignment
            return assignment

    def runtime_assignment(
        self,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        run_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> RuntimeAssignment | None:
        with self._lock:
            return self._runtime_assignments.get((world_id, branch_id, run_id, entity_id))

    def list_runtime_assignments(
        self,
        *,
        world_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[RuntimeAssignment, ...]:
        with self._lock:
            assignments = (
                item
                for item in self._runtime_assignments.values()
                if (world_id is None or item.world_id == world_id)
                and (branch_id is None or item.branch_id == branch_id)
                and (run_id is None or item.run_id == run_id)
                and (entity_id is None or item.entity_id == entity_id)
            )
            return tuple(
                sorted(
                    assignments,
                    key=lambda item: (
                        str(item.world_id),
                        str(item.branch_id),
                        str(item.run_id),
                        str(item.entity_id),
                    ),
                )
            )

    def record_decision(self, outcome: DecisionOutcome) -> DecisionOutcome:
        with self._lock:
            self._decisions.setdefault(outcome.trace.trace_id, outcome)
            return self._decisions[outcome.trace.trace_id]

    def inspect(self, entity_id: uuid.UUID, *, branch_id: uuid.UUID | None = None) -> dict:
        with self._lock:
            state = self._states.get(
                self._key(entity_id, branch_id), MindState(entity_id=entity_id)
            )
            return {
                "mind_state": state.model_dump(mode="json"),
                "observations": [
                    item.model_dump(mode="json")
                    for (observation_branch, _), item in self._observations.items()
                    if item.observer_entity_id == entity_id
                    and (branch_id is None or observation_branch == branch_id)
                ],
                "relationships": [
                    {
                        "target_entity_id": str(target),
                        **vector.model_dump(mode="json"),
                    }
                    for (relationship_branch, source, target), vector in self._relationships.items()
                    if source == entity_id
                    and (branch_id is None or relationship_branch == branch_id)
                ],
                "relationship_changes": [
                    item.model_dump(mode="json")
                    for (change_branch, _), item in self._relationship_changes.items()
                    if item.source_entity_id == entity_id
                    and (branch_id is None or change_branch == branch_id)
                ],
                "decisions": [
                    item.trace.model_dump(mode="json")
                    for item in self._decisions.values()
                    if item.proposal.embodied_entity_id == entity_id
                    and (branch_id is None or item.proposal.branch_id == branch_id)
                ],
            }
