from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg2.extras

from cognition.engine import DecisionOutcome, SubjectiveUpdate
from cognition.models import (
    Belief,
    Memory,
    MindState,
    Observation,
    RelationshipVector,
    RuntimeAssignment,
)
from cognition.relationships import RelationshipChangeRecord
from kernel.database import transaction


class PostgresMindRepository:
    """Durable subjective projections and immutable cognition evidence."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def save_decision(self, outcome: DecisionOutcome) -> None:
        proposal, trace = outcome.proposal, outcome.trace
        if proposal.embodied_entity_id is None:
            raise ValueError("durable decision traces require an embodied entity")
        with transaction(actor_id=proposal.actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cognition.decision_traces (
                      id, world_id, branch_id, run_id, entity_id, persona_id,
                      persona_version_id, policy_version, runtime_kind,
                      model_version, prompt_contract_version, seed, candidates,
                      chosen_action, explanation
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb
                    ) ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(trace.trace_id),
                        str(proposal.world_id),
                        str(proposal.branch_id),
                        str(proposal.run_id),
                        str(proposal.embodied_entity_id),
                        str(trace.persona_id),
                        trace.persona_version,
                        trace.policy_version,
                        trace.runtime_kind,
                        trace.model_version,
                        trace.prompt_contract_version,
                        trace.seed,
                        json.dumps([item.model_dump(mode="json") for item in trace.candidates]),
                        trace.chosen_action,
                        json.dumps(
                            {
                                "decision_tier": trace.decision_tier,
                                "rationale": trace.rationale,
                                "fallback_reason": trace.fallback_reason,
                                "plan": trace.plan,
                            }
                        ),
                    ),
                )

    def save_subjective_update(
        self,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        actor_id: uuid.UUID,
        state: MindState,
        update: SubjectiveUpdate,
    ) -> None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cognition.mind_states (
                      world_id, branch_id, entity_id, mood, stress,
                      attention_budget, active_plan, goals, needs
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
                    ON CONFLICT (world_id, branch_id, entity_id) DO UPDATE SET
                      mood = EXCLUDED.mood, stress = EXCLUDED.stress,
                      attention_budget = EXCLUDED.attention_budget,
                      active_plan = EXCLUDED.active_plan, goals = EXCLUDED.goals,
                      needs = EXCLUDED.needs, updated_at = now()
                    """,
                    (
                        str(world_id),
                        str(branch_id),
                        str(state.entity_id),
                        state.mood,
                        state.stress,
                        state.attention_budget,
                        json.dumps(state.active_plan),
                        json.dumps(state.goals),
                        json.dumps(state.needs),
                    ),
                )
                if update.observation is not None:
                    observation = update.observation
                    cursor.execute(
                        """
                        INSERT INTO cognition.observations (
                          id, world_id, branch_id, observer_entity_id,
                          source_event_id, perceived_payload, confidence, observed_at
                        ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(observation.observation_id),
                            str(world_id),
                            str(branch_id),
                            str(observation.observer_entity_id),
                            str(observation.source_event_id),
                            json.dumps(observation.perceived_payload, default=str),
                            observation.confidence,
                            observation.observed_at,
                        ),
                    )
                for belief in state.beliefs:
                    cursor.execute(
                        """
                        INSERT INTO cognition.beliefs (
                          id, world_id, branch_id, entity_id, subject_type,
                          subject_id, predicate, value, confidence,
                          source_observation_id, contradicted_by_event_id, updated_at
                        ) VALUES (
                          %s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s
                        ) ON CONFLICT (id) DO UPDATE SET
                          value = EXCLUDED.value, confidence = EXCLUDED.confidence,
                          source_observation_id = EXCLUDED.source_observation_id,
                          contradicted_by_event_id = EXCLUDED.contradicted_by_event_id,
                          updated_at = EXCLUDED.updated_at
                        """,
                        (
                            str(belief.belief_id),
                            str(world_id),
                            str(branch_id),
                            str(belief.entity_id),
                            belief.subject_type,
                            str(belief.subject_id) if belief.subject_id else None,
                            belief.predicate,
                            json.dumps(belief.value, default=str),
                            belief.confidence,
                            str(belief.source_observation_id)
                            if belief.source_observation_id
                            else None,
                            str(belief.contradicted_by_event_id)
                            if belief.contradicted_by_event_id
                            else None,
                            belief.updated_at,
                        ),
                    )
                if update.memory is not None:
                    memory = update.memory
                    cursor.execute(
                        """
                        INSERT INTO cognition.memories (
                          id, world_id, branch_id, entity_id, source_event_id,
                          source_observation_id,
                          summary, emotional_weight, importance, recall_strength,
                          visibility, created_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(memory.memory_id),
                            str(world_id),
                            str(branch_id),
                            str(memory.entity_id),
                            str(memory.source_event_id),
                            str(memory.source_observation_id)
                            if memory.source_observation_id
                            else None,
                            memory.summary,
                            memory.emotional_weight,
                            memory.importance,
                            memory.recall_strength,
                            memory.visibility,
                            memory.created_at,
                        ),
                    )
                for evidence in update.evidence:
                    cursor.execute(
                        """
                        INSERT INTO cognition.belief_evidence (
                          id, world_id, branch_id, entity_id, belief_id,
                          source_observation_id, evidence_type,
                          immediate_source_entity_id, claimed_origin_event_id,
                          parent_evidence_id, direct_witness, confidence_modifier,
                          created_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            str(evidence.evidence_id),
                            str(evidence.world_id),
                            str(evidence.branch_id),
                            str(evidence.entity_id),
                            str(evidence.belief_id) if evidence.belief_id else None,
                            str(evidence.source_observation_id),
                            evidence.evidence_type,
                            str(evidence.immediate_source_entity_id)
                            if evidence.immediate_source_entity_id
                            else None,
                            str(evidence.claimed_origin_event_id)
                            if evidence.claimed_origin_event_id
                            else None,
                            str(evidence.parent_evidence_id)
                            if evidence.parent_evidence_id
                            else None,
                            evidence.direct_witness,
                            evidence.confidence_modifier,
                            evidence.created_at,
                        ),
                    )

    def save_runtime_assignment(
        self,
        assignment: RuntimeAssignment,
        *,
        actor_id: uuid.UUID,
    ) -> RuntimeAssignment:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO cognition.runtime_assignments (
                      world_id, branch_id, run_id, entity_id,
                      runtime_kind, runtime_config, assigned_at
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                    ON CONFLICT (world_id, branch_id, run_id, entity_id) DO UPDATE SET
                      runtime_kind = EXCLUDED.runtime_kind,
                      runtime_config = EXCLUDED.runtime_config,
                      assigned_at = EXCLUDED.assigned_at
                    RETURNING *
                    """,
                    (
                        str(assignment.world_id),
                        str(assignment.branch_id),
                        str(assignment.run_id),
                        str(assignment.entity_id),
                        assignment.runtime_kind,
                        json.dumps(assignment.runtime_config),
                        assignment.assigned_at,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise PermissionError("actor cannot assign this entity runtime")
                return self._runtime_assignment(row)

    def load_runtime_assignment(
        self,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        run_id: uuid.UUID,
        entity_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> RuntimeAssignment | None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT * FROM cognition.runtime_assignments
                    WHERE world_id=%s AND branch_id=%s AND run_id=%s AND entity_id=%s""",
                    (str(world_id), str(branch_id), str(run_id), str(entity_id)),
                )
                row = cursor.fetchone()
                return self._runtime_assignment(row) if row is not None else None

    def list_runtime_assignments(
        self,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        actor_id: uuid.UUID,
        run_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[RuntimeAssignment, ...]:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """SELECT * FROM cognition.runtime_assignments
                    WHERE world_id=%s AND branch_id=%s
                      AND (%s::uuid IS NULL OR run_id=%s::uuid)
                      AND (%s::uuid IS NULL OR entity_id=%s::uuid)
                    ORDER BY run_id, entity_id""",
                    (
                        str(world_id),
                        str(branch_id),
                        str(run_id) if run_id is not None else None,
                        str(run_id) if run_id is not None else None,
                        str(entity_id) if entity_id is not None else None,
                        str(entity_id) if entity_id is not None else None,
                    ),
                )
                return tuple(self._runtime_assignment(row) for row in cursor.fetchall())

    @staticmethod
    def _runtime_assignment(row: dict[str, Any]) -> RuntimeAssignment:
        return RuntimeAssignment(
            world_id=row["world_id"],
            branch_id=row["branch_id"],
            run_id=row["run_id"],
            entity_id=row["entity_id"],
            runtime_kind=row["runtime_kind"],
            runtime_config=row["runtime_config"],
            assigned_at=row["assigned_at"],
        )

    def get_relationship_change(
        self, change_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> RelationshipChangeRecord | None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                return self._load_relationship_change(cursor, change_id)

    def save_relationship_change(
        self, record: RelationshipChangeRecord
    ) -> RelationshipChangeRecord:
        """Atomically append causal evidence and advance its relationship projection."""

        if record.source_entity_id == record.target_entity_id:
            raise ValueError("self relationships are not supported")
        with transaction(actor_id=record.actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT event_id, world_id, branch_id
                    FROM sim.events
                    WHERE event_id=%s
                    """,
                    (str(record.source_event_id),),
                )
                source_event = cursor.fetchone()
                if source_event is None:
                    raise ValueError("relationship source event is unavailable to actor")
                if (
                    uuid.UUID(str(source_event["world_id"])) != record.world_id
                    or uuid.UUID(str(source_event["branch_id"])) != record.branch_id
                ):
                    raise ValueError("relationship source event must share the entity world branch")

                existing = self._load_relationship_change(cursor, record.change_id)
                if existing is not None:
                    self._validate_relationship_retry(existing, record)
                    return existing

                cursor.execute(
                    """
                    INSERT INTO cognition.relationships (
                      world_id, branch_id, source_entity_id, target_entity_id
                    ) VALUES (%s,%s,%s,%s)
                    ON CONFLICT (
                      world_id, branch_id, source_entity_id, target_entity_id
                    ) DO NOTHING
                    """,
                    (
                        str(record.world_id),
                        str(record.branch_id),
                        str(record.source_entity_id),
                        str(record.target_entity_id),
                    ),
                )
                cursor.execute(
                    """
                    SELECT * FROM cognition.relationships
                    WHERE world_id=%s AND branch_id=%s
                      AND source_entity_id=%s AND target_entity_id=%s
                    FOR UPDATE
                    """,
                    (
                        str(record.world_id),
                        str(record.branch_id),
                        str(record.source_entity_id),
                        str(record.target_entity_id),
                    ),
                )
                projection_row = cursor.fetchone()
                if projection_row is None:
                    raise PermissionError("actor cannot update this relationship")

                existing = self._load_relationship_change(cursor, record.change_id)
                if existing is not None:
                    self._validate_relationship_retry(existing, record)
                    return existing

                current = RelationshipVector.model_validate(
                    {name: projection_row[name] for name in RelationshipVector.model_fields}
                )
                if current != record.before:
                    raise ValueError("relationship projection changed before causal update")

                cursor.execute(
                    """
                    INSERT INTO cognition.relationship_changes (
                      id, world_id, branch_id, source_entity_id, target_entity_id,
                      source_event_id, actor_id, event_type, policy_version,
                      requested_deltas, applied_deltas, before_vector, after_vector,
                      created_at
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,
                      %s::jsonb,%s
                    )
                    """,
                    (
                        str(record.change_id),
                        str(record.world_id),
                        str(record.branch_id),
                        str(record.source_entity_id),
                        str(record.target_entity_id),
                        str(record.source_event_id),
                        str(record.actor_id),
                        record.event_type,
                        record.policy_version,
                        json.dumps(record.requested_deltas),
                        json.dumps(record.applied_deltas),
                        record.before.model_dump_json(),
                        record.after.model_dump_json(),
                        record.created_at,
                    ),
                )
                values = record.after.model_dump()
                cursor.execute(
                    """
                    UPDATE cognition.relationships SET
                      trust=%s, affection=%s, respect=%s, fear=%s,
                      resentment=%s, obligation=%s, familiarity=%s,
                      suspicion=%s, ideological_alignment=%s, dependency=%s,
                      attraction=%s, updated_at=now()
                    WHERE world_id=%s AND branch_id=%s
                      AND source_entity_id=%s AND target_entity_id=%s
                    """,
                    (
                        *(
                            values[name]
                            for name in (
                                "trust",
                                "affection",
                                "respect",
                                "fear",
                                "resentment",
                                "obligation",
                                "familiarity",
                                "suspicion",
                                "ideological_alignment",
                                "dependency",
                                "attraction",
                            )
                        ),
                        str(record.world_id),
                        str(record.branch_id),
                        str(record.source_entity_id),
                        str(record.target_entity_id),
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("relationship projection update was not applied")
                return record

    @staticmethod
    def _load_relationship_change(
        cursor: Any, change_id: uuid.UUID
    ) -> RelationshipChangeRecord | None:
        cursor.execute(
            "SELECT * FROM cognition.relationship_changes WHERE id=%s",
            (str(change_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return RelationshipChangeRecord(
            change_id=row["id"],
            world_id=row["world_id"],
            branch_id=row["branch_id"],
            source_entity_id=row["source_entity_id"],
            target_entity_id=row["target_entity_id"],
            source_event_id=row["source_event_id"],
            actor_id=row["actor_id"],
            event_type=row["event_type"],
            policy_version=row["policy_version"],
            requested_deltas=row["requested_deltas"],
            applied_deltas=row["applied_deltas"],
            before=row["before_vector"],
            after=row["after_vector"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _validate_relationship_retry(
        existing: RelationshipChangeRecord,
        requested: RelationshipChangeRecord,
    ) -> None:
        if existing.immutable_content() != requested.immutable_content():
            raise ValueError("relationship change retry differs from immutable history")

    def inspect(
        self,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        entity_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> dict[str, Any]:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                context = (str(world_id), str(branch_id), str(entity_id))
                cursor.execute(
                    """SELECT * FROM cognition.mind_states
                    WHERE world_id=%s AND branch_id=%s AND entity_id=%s""",
                    context,
                )
                mind = cursor.fetchone()
                collections: dict[str, list[dict[str, Any]]] = {}
                for name, column, ordering in (
                    ("observations", "observer_entity_id", "observed_at, id"),
                    ("beliefs", "entity_id", "updated_at, id"),
                    ("memories", "entity_id", "created_at, id"),
                ):
                    cursor.execute(
                        f"""SELECT * FROM cognition.{name}
                        WHERE world_id=%s AND branch_id=%s AND {column}=%s
                        ORDER BY {ordering}""",
                        context,
                    )
                    collections[name] = [dict(item) for item in cursor.fetchall()]
                cursor.execute(
                    """SELECT * FROM cognition.belief_evidence
                    WHERE world_id=%s AND branch_id=%s AND entity_id=%s
                    ORDER BY created_at, id""",
                    context,
                )
                collections["belief_evidence"] = [dict(item) for item in cursor.fetchall()]
                cursor.execute(
                    """SELECT * FROM cognition.relationships
                    WHERE world_id=%s AND branch_id=%s AND source_entity_id=%s
                    ORDER BY target_entity_id""",
                    context,
                )
                relationships = [dict(item) for item in cursor.fetchall()]
                cursor.execute(
                    """SELECT * FROM cognition.relationship_changes
                    WHERE world_id=%s AND branch_id=%s AND source_entity_id=%s
                    ORDER BY created_at, id""",
                    context,
                )
                relationship_changes = [dict(item) for item in cursor.fetchall()]
                cursor.execute(
                    """SELECT * FROM cognition.decision_traces
                    WHERE world_id=%s AND branch_id=%s AND entity_id=%s
                    ORDER BY created_at, id""",
                    context,
                )
                decisions = [dict(item) for item in cursor.fetchall()]
        return {
            "mind_state": dict(mind) if mind is not None else None,
            **collections,
            "relationships": relationships,
            "relationship_changes": relationship_changes,
            "decisions": decisions,
        }

    def load_projection(
        self,
        *,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        entity_id: uuid.UUID,
        actor_id: uuid.UUID,
    ) -> tuple[
        MindState,
        tuple[Observation, ...],
        tuple[tuple[uuid.UUID, RelationshipVector], ...],
    ]:
        """Load the branch-scoped subjective projection used by live cognition."""
        payload = self.inspect(
            world_id=world_id,
            branch_id=branch_id,
            entity_id=entity_id,
            actor_id=actor_id,
        )
        mind = payload["mind_state"] or {}
        beliefs = tuple(
            Belief(
                belief_id=row["id"],
                entity_id=row["entity_id"],
                subject_type=row["subject_type"],
                subject_id=row["subject_id"],
                predicate=row["predicate"],
                value=row["value"],
                confidence=row["confidence"],
                source_observation_id=row["source_observation_id"],
                contradicted_by_event_id=row["contradicted_by_event_id"],
                updated_at=row["updated_at"],
            )
            for row in payload["beliefs"]
        )
        memories = tuple(
            Memory(
                memory_id=row["id"],
                entity_id=row["entity_id"],
                source_event_id=row["source_event_id"],
                source_observation_id=row.get("source_observation_id"),
                summary=row["summary"],
                emotional_weight=row["emotional_weight"],
                importance=row["importance"],
                recall_strength=row["recall_strength"],
                visibility=row["visibility"],
                created_at=row["created_at"],
            )
            for row in payload["memories"]
        )
        observations = tuple(
            Observation(
                observation_id=row["id"],
                observer_entity_id=row["observer_entity_id"],
                source_event_id=row["source_event_id"],
                perceived_payload=row["perceived_payload"],
                confidence=row["confidence"],
                observed_at=row["observed_at"],
            )
            for row in payload["observations"]
        )
        relationships = tuple(
            (
                uuid.UUID(str(row["target_entity_id"])),
                RelationshipVector.model_validate(
                    {name: row[name] for name in RelationshipVector.model_fields}
                ),
            )
            for row in payload["relationships"]
        )
        return (
            MindState(
                entity_id=entity_id,
                mood=mind.get("mood", "NEUTRAL"),
                stress=mind.get("stress", 0),
                attention_budget=mind.get("attention_budget", 100),
                active_plan=tuple(mind.get("active_plan") or ()),
                goals=tuple(mind.get("goals") or ()),
                needs=dict(mind.get("needs") or {}),
                beliefs=beliefs,
                memories=memories,
            ),
            observations,
            relationships,
        )
