from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from cognition.control import execution_actor
from cognition.postgres_control import ensure_execution_actor
from kernel.campaign_checkpoints import CampaignCheckpoint, CheckpointSection
from kernel.campaign_revisions import (
    RESTORE_VERSION,
    CampaignRevisionPlan,
    archived_runs,
    build_paused_projection,
    restored_run_id,
)
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.checkpoint_knowledge import (
    RestoredKnowledge,
    Row,
    archived_rows,
    identifier_map,
    remap_row,
    restore_knowledge,
    restored_identity,
    scoped_copy,
)
from kernel.control import ControllerState, ControlScope
from kernel.postgres_campaign_checkpoints import CheckpointEvidence
from kernel.postgres_control_plane import PostgresControlPlane
from kernel.snapshots import SnapshotEntity, SnapshotStore
from kernel.state import stable_hash


@dataclass(frozen=True)
class RestoredCampaign:
    checkpoint: CampaignCheckpoint
    plan: CampaignRevisionPlan
    projection: dict[str, dict]
    run_ids: dict[str, str]
    knowledge: RestoredKnowledge

    @classmethod
    def build(
        cls,
        checkpoint: CampaignCheckpoint,
        evidence: CheckpointEvidence,
        plan: CampaignRevisionPlan,
    ) -> RestoredCampaign:
        runs = archived_runs(checkpoint)
        if plan.source_live_run_id not in runs:
            raise CheckpointHoldConflict("the planned run is absent from the archive")
        run_ids = {
            str(source): str(restored_run_id(plan.successor_branch_id, source)) for source in runs
        }
        if run_ids[str(plan.source_live_run_id)] != str(plan.successor_run_id):
            raise CheckpointHoldConflict("the planned successor run is inconsistent")
        projection = build_paused_projection(checkpoint, plan.successor_branch_id, runs)
        version = plan.provenance.restore_version
        planned_projection = (
            build_paused_projection(checkpoint, plan.successor_branch_id, runs, version=version)
            if version != RESTORE_VERSION
            else projection
        )
        knowledge = restore_knowledge(checkpoint, evidence, plan.successor_branch_id, run_ids)
        if stable_hash(planned_projection) != plan.candidate_state_hash or (
            plan.provenance.retained_knowledge_hash is not None
            and knowledge.digest != plan.provenance.retained_knowledge_hash
        ):
            raise CheckpointHoldConflict("the archived state differs from the prepared revision")
        if version == "campaign-restore-1.1.0" and planned_projection != projection:
            raise CheckpointHoldConflict(
                "prepare a new revision to restore these campaign mechanics"
            )
        return cls(checkpoint, plan, projection, run_ids, knowledge)

    def source(
        self, section: CheckpointSection, table: str, *, optional: bool = False
    ) -> tuple[Row, ...]:
        component = self.checkpoint.sections[section]
        if optional and getattr(component, "data", {}).get(table) is None:
            return ()
        return archived_rows(self.checkpoint, section, table)

    def copy(
        self,
        row: Row,
        mapping: Mapping[str, Mapping[str, str]],
        *,
        bodies: tuple[str, ...] = (),
        required: frozenset[str] = frozenset(),
    ) -> Row:
        return remap_row(
            scoped_copy(row, self.checkpoint, self.plan.successor_branch_id, bodies=bodies),
            mapping,
            required,
        )


def insert_rows(cursor: RealDictCursor, table: str, rows: Sequence[Row]) -> None:
    if not rows:
        return
    columns = sorted(rows[0])
    if any(sorted(row) != columns for row in rows):
        raise CheckpointHoldConflict("restored rows have incompatible columns")
    name = sql.Identifier(*table.split("."))
    fields = sql.SQL(",").join(sql.Identifier(column) for column in columns)
    cursor.execute(
        sql.SQL(
            "INSERT INTO {table} ({fields}) SELECT {fields} "
            "FROM jsonb_populate_recordset(NULL::{table},%s::jsonb) WITH ORDINALITY AS restored "
            "ORDER BY restored.ordinality"
        ).format(table=name, fields=fields),
        (json.dumps(rows),),
    )


def restore_entities(
    cursor: RealDictCursor, campaign: RestoredCampaign
) -> dict[str, SnapshotEntity]:
    plan = campaign.plan
    cursor.execute(
        """SELECT e.id,e.controller_actor_id FROM sim.entities e
           JOIN sim.actors a ON a.id=e.controller_actor_id AND a.is_active
           JOIN sim.actor_capabilities grant_row ON
            (grant_row.world_id,grant_row.actor_id)=(e.world_id,e.controller_actor_id)
            AND grant_row.capability='entity.act'
           WHERE (e.world_id,e.branch_id)=(%s,%s)""",
        (str(plan.world_id), str(plan.branch_id)),
    )
    current = {str(row["id"]): row["controller_actor_id"] for row in cursor}
    metadata = {}
    bodies = []
    for key, source in sorted(campaign.checkpoint.entities.items()):
        state = campaign.projection["tabletop.entities"][key]
        owner = uuid.UUID(str(current[key])) if key in current else None
        item = SnapshotEntity(
            entity_id=source.entity_id,
            world_id=source.world_id,
            branch_id=plan.successor_branch_id,
            entity_type=state["entity_type"],
            name=state["name"],
            controller_actor_id=owner,
            secret_state=source.secret_state,
        )
        metadata[key] = item
        row = item.model_dump(mode="json", exclude={"entity_id"})
        row["id"] = key
        row["public_state"] = {k: v for k, v in state.items() if k not in {"name", "entity_type"}}
        bodies.append(row)
    insert_rows(cursor, "sim.entities", bodies)
    return metadata


def restore_runtime(cursor: RealDictCursor, campaign: RestoredCampaign) -> None:
    plan = campaign.plan
    source = campaign.source
    runtime = CheckpointSection.CHARACTER_RUNTIME
    pending = CheckpointSection.PENDING_WORK
    target = plan.successor_branch_id
    old_runs = source(CheckpointSection.RANDOMNESS, "runs")
    new_runs = []
    for row in old_runs:
        run = campaign.copy(row, {"id": campaign.run_ids}, required=frozenset({"id"}))
        run["model_assignment"] = {}
        if run["status"] in {"QUEUED", "RUNNING", "PAUSED"}:
            run["status"] = "PAUSED"
        if str(row["id"]) == str(plan.source_live_run_id):
            run["seed"] = plan.seed
        new_runs.append(run)
    insert_rows(cursor, "sim.runs", new_runs)
    interactions = source(pending, "sim.interactions")
    interaction_ids = identifier_map(target, "interaction", interactions, "id")
    insert_rows(
        cursor,
        "sim.interactions",
        [
            campaign.copy(
                row,
                {"id": interaction_ids, "run_id": campaign.run_ids},
                required=frozenset({"id", "run_id"}),
            )
            for row in interactions
        ],
    )
    traces = source(runtime, "cognition.decision_traces")
    trace_ids = identifier_map(target, "decision-trace", traces, "id")
    committed = {row["decision_trace_id"] for row in campaign.knowledge.events}
    insert_rows(
        cursor,
        "cognition.decision_traces",
        [
            campaign.copy(
                row,
                {"id": trace_ids, "run_id": campaign.run_ids},
                bodies=("entity_id",),
                required=frozenset({"id", "run_id"}),
            )
            for row in traces
            if trace_ids[row["id"]] in committed
        ],
    )
    insert_rows(
        cursor,
        "persona.entity_assignments",
        [
            campaign.copy(row, {}, bodies=("entity_id",))
            for row in source(runtime, "persona.entity_assignments")
        ],
    )
    insert_rows(
        cursor,
        "cognition.runtime_assignments",
        [
            campaign.copy(
                row,
                {"run_id": campaign.run_ids},
                bodies=("entity_id",),
                required=frozenset({"run_id"}),
            )
            for row in source(runtime, "cognition.runtime_assignments")
        ],
    )
    controllers = []
    for row in source(runtime, "cognition.controller_assignments"):
        copy = campaign.copy(
            row,
            {"run_id": campaign.run_ids},
            bodies=("entity_id",),
            required=frozenset({"run_id"}),
        )
        archived = ControllerState.model_validate(row["payload"])
        scope = ControlScope(
            world_id=plan.world_id,
            branch_id=target,
            run_id=uuid.UUID(copy["run_id"]),
            entity_id=archived.entity_id,
        )
        executor = execution_actor(scope)
        ensure_execution_actor(cursor, scope.world_id, executor)
        copy["executor_actor_id"] = str(executor)
        copy["payload"] = archived.model_copy(
            update={
                "branch_id": scope.branch_id,
                "run_id": scope.run_id,
                "executor_actor_id": executor,
                "epoch": 1,
                "mode": "PAUSED",
                "failures": 0,
                "last_error": None,
                "presence_deadline_at": None,
                "handoff_reason": None,
            }
        ).model_dump(mode="json")
        controllers.append(copy)
    insert_rows(cursor, "cognition.controller_assignments", controllers)


def restore_bindings(cursor: RealDictCursor, campaign: RestoredCampaign) -> dict[str, str]:
    bindings = campaign.source(CheckpointSection.CHARACTER_RUNTIME, "tabletop.character_bindings")
    identities = identifier_map(
        campaign.plan.successor_branch_id, "binding", bindings, "binding_id"
    )
    copies = []
    for row in sorted(bindings, key=lambda item: item["sequence"]):
        restored = campaign.copy(
            row,
            {
                "binding_id": identities,
                "replaces_binding_id": identities,
                "run_id": campaign.run_ids,
            },
            bodies=("entity_id",),
            required=frozenset({"binding_id", "run_id"}),
        )
        restored.pop("sequence")
        copies.append(restored)
    # The binding lineage trigger observes each prior revision by its new sequence.
    for row in copies:
        insert_rows(cursor, "tabletop.character_bindings", [row])
    return identities


def restore_population(cursor: RealDictCursor, campaign: RestoredCampaign) -> None:
    kind = CheckpointSection.POPULATION
    target = campaign.plan.successor_branch_id
    definitions = campaign.source(kind, "population.definitions")
    pools = campaign.source(kind, "population.pools")
    cohorts = campaign.source(kind, "population.cohorts")
    people = campaign.source(kind, "population.materialized_people")
    transitions = campaign.source(kind, "population.lifecycle_transitions")
    definition_ids = identifier_map(target, "population", definitions, "id")
    pool_ids = identifier_map(target, "population-pool", pools, "id")
    cohort_ids = identifier_map(target, "population-cohort", cohorts, "id")
    # The root catalog's natural key is globally unique. Keep the original rule version.
    new_definitions = []
    for row in definitions:
        if row["world_id"] != str(campaign.plan.world_id):
            raise CheckpointHoldConflict(
                "checkpoint population source belongs to a different world"
            )
        copied = remap_row(row, {"id": definition_ids}, frozenset({"id"}))
        copied["branch_id"] = str(target)
        copied["population_key"] = f"{row['population_key']}@{target}"
        new_definitions.append(copied)
    insert_rows(cursor, "population.definitions", new_definitions)
    insert_rows(
        cursor,
        "population.pools",
        [
            remap_row(
                row,
                {"id": pool_ids, "definition_id": definition_ids},
                frozenset({"id", "definition_id"}),
            )
            for row in pools
        ],
    )
    insert_rows(
        cursor,
        "population.cohorts",
        [
            remap_row(row, {"id": cohort_ids, "pool_id": pool_ids}, frozenset({"id", "pool_id"}))
            for row in cohorts
        ],
    )
    person_ids = identifier_map(target, "person", people, "id")
    insert_rows(
        cursor,
        "population.materialized_people",
        [
            campaign.copy(
                row,
                {
                    "id": person_ids,
                    "population_id": definition_ids,
                    "binding_event_id": campaign.knowledge.event_origins,
                },
                bodies=("entity_id",) if row["entity_id"] is not None else (),
                required=frozenset({"id", "population_id"}),
            )
            for row in people
        ],
    )
    transition_ids = identifier_map(target, "lifecycle-transition", transitions, "transition_id")
    insert_rows(
        cursor,
        "population.lifecycle_transitions",
        [
            campaign.copy(
                row,
                {"transition_id": transition_ids, "population_id": definition_ids},
                required=frozenset({"transition_id", "population_id"}),
            )
            for row in transitions
        ],
    )


def restore_behavior(
    cursor: RealDictCursor, campaign: RestoredCampaign, bindings: dict[str, str]
) -> None:
    for table in ("cognition.human_movement_evidence", "cognition.human_choice_evidence"):
        rows = []
        for original in sorted(
            campaign.source(CheckpointSection.CHARACTER_RUNTIME, table),
            key=lambda row: row["sequence"],
        ):
            copy = campaign.copy(
                original,
                {
                    "event_id": campaign.knowledge.event_origins,
                    "run_id": campaign.run_ids,
                    "binding_id": bindings,
                },
                bodies=("entity_id",),
                required=frozenset({"event_id", "run_id", "binding_id"}),
            )
            copy.pop("sequence")
            copy["payload"] = {
                **copy["payload"],
                **{key: copy[key] for key in ("branch_id", "run_id", "binding_id")},
            }
            rows.append(copy)
        insert_rows(cursor, table, rows)


def restore_schedules(cursor: RealDictCursor, campaign: RestoredCampaign) -> None:
    pending = CheckpointSection.PENDING_WORK
    target = campaign.plan.successor_branch_id
    scheduled = campaign.source(pending, "sim.schedules")
    schedules = identifier_map(target, "schedule", scheduled, "id")
    insert_rows(
        cursor,
        "sim.schedules",
        [campaign.copy(row, {"id": schedules}, required=frozenset({"id"})) for row in scheduled],
    )
    rules = campaign.source(pending, "sim.campaign_checkpoint_rules", optional=True)
    retained = []
    for row in rules:
        if row["active"]:
            copy = campaign.copy(row, {})
            copy["rule_id"] = restored_identity(target, "checkpoint-rule", row["rule_id"])
            retained.append(copy)
    insert_rows(cursor, "sim.campaign_checkpoint_rules", retained)


def persist_restored_campaign(
    cursor: RealDictCursor,
    campaign: RestoredCampaign,
    control: PostgresControlPlane,
    snapshots: SnapshotStore,
) -> None:
    plan = campaign.plan
    version = campaign.checkpoint.boundary.projection_version
    insert_rows(
        cursor,
        "sim.branch_projections",
        [
            {
                "world_id": str(plan.world_id),
                "branch_id": str(plan.successor_branch_id),
                "version": version,
                "state": campaign.projection,
                "state_hash": stable_hash(campaign.projection),
            }
        ],
    )
    entities = restore_entities(cursor, campaign)
    restore_runtime(cursor, campaign)
    insert_rows(cursor, "sim.events", campaign.knowledge.events)
    insert_rows(
        cursor,
        "sim.campaign_revision_event_origins",
        [
            {
                "world_id": str(plan.world_id),
                "branch_id": str(plan.successor_branch_id),
                "source_branch_id": str(plan.branch_id),
                "source_event_id": source,
                "event_id": event,
            }
            for source, event in campaign.knowledge.event_origins.items()
        ],
    )
    insert_rows(cursor, "sim.event_perceptions", campaign.knowledge.perceptions)
    for table, rows in campaign.knowledge.subjective.items():
        insert_rows(cursor, table, rows)
    bindings = restore_bindings(cursor, campaign)
    restore_behavior(cursor, campaign, bindings)
    restore_population(cursor, campaign)
    restore_schedules(cursor, campaign)
    snapshot = snapshots.create(
        plan.world_id, plan.successor_branch_id, 0, campaign.projection, entities=entities
    )
    control.persist_snapshot(snapshot, version, cursor=cursor)
