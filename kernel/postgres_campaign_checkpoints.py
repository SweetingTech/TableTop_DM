from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any, cast

import psycopg2.errors
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue

from cognition.knowledge import KNOWLEDGE_VERSION
from cognition.narration import NARRATION_VERSION
from kernel.campaign_checkpoints import (
    AbsentComponent,
    CampaignCheckpoint,
    CampaignCheckpointManifest,
    CampaignCheckpointStore,
    CheckpointBoundary,
    CheckpointReference,
    CheckpointSection,
    FrozenComponent,
    PinnedComponent,
    RebuildComponent,
)
from kernel.checkpoint_holds import CheckpointHold, CheckpointHoldConflict, PostgresCheckpointHolds
from kernel.database import transaction
from kernel.postgres_control_plane import read_snapshot_entities
from kernel.snapshots import artifact_path
from kernel.state import stable_hash


class CheckpointReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    manifest: CampaignCheckpointManifest
    label: str
    created_at: AwareDatetime


def read_scoped_rows(
    cursor: RealDictCursor,
    scope: tuple[str, str],
    table: str,
    *,
    order: tuple[str, ...] = (),
    omit: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    # All table, column, and exclusion names come from the server's capture plan.
    row_data: sql.Composable = sql.SQL("to_jsonb(row)")
    if omit:
        row_data = sql.SQL("{} - {}::text[]").format(row_data, sql.Literal(list(omit)))
    ordering = (
        sql.SQL(", ").join(sql.Identifier(name) for name in order)
        if order
        else sql.SQL("to_jsonb(row)::text")
    )
    cursor.execute(
        sql.SQL(
            "SELECT {} AS payload FROM {} row WHERE (world_id,branch_id)=(%s,%s) ORDER BY {}"
        ).format(row_data, sql.Identifier(*table.split(".")), ordering),
        scope,
    )
    return [row["payload"] for row in cursor]


def frozen_tables(
    cursor: RealDictCursor, scope: tuple[str, str], schema_id: str, *tables: str
) -> FrozenComponent:
    return FrozenComponent(
        schema_id=schema_id,
        data={table: read_scoped_rows(cursor, scope, table) for table in tables},
    )


def sorted_references(references: list[CheckpointReference]) -> tuple[CheckpointReference, ...]:
    return tuple(sorted(references, key=lambda item: (item.kind, item.identity, item.version)))


def pin_artifacts(
    cursor: RealDictCursor, scope: tuple[str, str], artifacts_root: Path
) -> PinnedComponent:
    references: list[CheckpointReference] = []
    cursor.execute(
        """SELECT revision.revision_id,revision.revision_number,revision.content
        FROM tabletop.character_card_revisions revision
        WHERE EXISTS (
          SELECT 1 FROM tabletop.character_bindings binding
          WHERE (binding.world_id,binding.branch_id)=(%s,%s)
            AND binding.card_revision_id=revision.revision_id
        )""",
        scope,
    )
    cards = cursor.fetchall()
    cursor.execute(
        "SELECT count(DISTINCT card_revision_id) AS n FROM tabletop.character_bindings "
        "WHERE (world_id,branch_id)=(%s,%s)",
        scope,
    )
    card_count = cursor.fetchone()
    if card_count is None or card_count["n"] != len(cards):
        raise ValueError("checkpoint is missing a bound authored revision")
    references.extend(
        CheckpointReference(
            kind="authored-card",
            identity=str(row["revision_id"]),
            version=str(row["revision_number"]),
            digest=stable_hash(row["content"]),
        )
        for row in cards
    )
    cursor.execute(
        """WITH reachable AS (
          SELECT persona_id,persona_version_id FROM tabletop.character_bindings
          WHERE (world_id,branch_id)=(%s,%s)
          UNION SELECT persona_id,persona_version_id FROM persona.entity_assignments
          WHERE (world_id,branch_id)=(%s,%s)
          UNION SELECT persona_id,persona_version_id FROM population.materialized_people
          WHERE (world_id,branch_id)=(%s,%s)
        ) SELECT b.version_id,b.schema_version,b.content_hash,s.schema_hash
          FROM reachable r JOIN persona.blueprints b
            ON (b.persona_id,b.version_id)=(r.persona_id,r.persona_version_id)
          JOIN persona.schema_versions s ON s.version=b.schema_version""",
        scope * 3,
    )
    schemas: dict[str, str] = {}
    for row in cursor:
        schema = row["schema_version"]
        schemas[schema] = row["schema_hash"]
        references.append(
            CheckpointReference(
                kind="persona-blueprint",
                identity=str(row["version_id"]),
                version=schema,
                digest=row["content_hash"],
            )
        )
    references.extend(
        CheckpointReference(kind="persona-schema", identity=key, version=key, digest=digest)
        for key, digest in schemas.items()
    )
    cursor.execute(
        """SELECT profile.persona_version_id,profile.compiler_version,to_jsonb(profile) AS payload
        FROM persona.compiled_profiles profile
        WHERE EXISTS (
          SELECT 1 FROM tabletop.character_bindings binding
          WHERE (binding.world_id,binding.branch_id)=(%s,%s)
            AND (binding.persona_id,binding.persona_version_id,binding.compiler_version) =
              (profile.persona_id,profile.persona_version_id,profile.compiler_version)
        )""",
        scope,
    )
    references.extend(
        CheckpointReference(
            kind="compiled-persona",
            identity=str(row["persona_version_id"]),
            version=row["compiler_version"],
            digest=stable_hash(row["payload"]),
        )
        for row in cursor
    )
    cursor.execute(
        """SELECT artifact.id,artifact.artifact_kind,artifact.content_hash,artifact.uri
        FROM artifacts.objects artifact WHERE EXISTS (
          SELECT 1 FROM population.pools pool JOIN population.definitions definition
            ON definition.id=pool.definition_id
          WHERE pool.artifact_id=artifact.id AND (
            (definition.world_id,definition.branch_id)=(%s,%s) OR EXISTS (
              SELECT 1 FROM population.materialized_people person
              WHERE (person.world_id,person.branch_id)=(%s,%s)
                AND person.population_id=definition.id
            )
          )
        ) OR EXISTS (
          SELECT 1 FROM cognition.decision_traces trace
          WHERE (trace.world_id,trace.branch_id)=(%s,%s) AND trace.artifact_id=artifact.id
        )""",
        scope * 3,
    )
    for row in cursor:
        try:
            path = artifact_path(row["uri"]).resolve(strict=True)
            if not path.is_relative_to(artifacts_root):
                raise ValueError("source is outside the archive root")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != row["content_hash"]:
                raise ValueError("source digest differs")
        except (OSError, ValueError):
            raise CheckpointHoldConflict("a checkpoint source artifact is unavailable") from None
        references.append(
            CheckpointReference(
                kind="artifact",
                identity=str(row["id"]),
                version=row["artifact_kind"],
                digest=digest,
            )
        )
    return PinnedComponent(
        schema_id="versioned-artifacts/v1", references=sorted_references(references)
    )


def collect_population(cursor: RealDictCursor, scope: tuple[str, str]) -> FrozenComponent:
    cursor.execute(
        """SELECT to_jsonb(definition) AS payload FROM population.definitions definition
        WHERE (definition.world_id,definition.branch_id)=(%s,%s) OR EXISTS (
          SELECT 1 FROM population.materialized_people person
          WHERE (person.world_id,person.branch_id)=(%s,%s) AND person.population_id=definition.id
        ) ORDER BY definition.id""",
        scope * 2,
    )
    definitions = [row["payload"] for row in cursor]
    cursor.execute(
        "SELECT to_jsonb(pool) AS payload FROM population.pools pool "
        "WHERE pool.definition_id=ANY(%s::uuid[]) ORDER BY pool.id",
        ([row["id"] for row in definitions],),
    )
    pools = [row["payload"] for row in cursor]
    cursor.execute(
        "SELECT to_jsonb(cohort) AS payload FROM population.cohorts cohort "
        "WHERE cohort.pool_id=ANY(%s::uuid[]) ORDER BY cohort.id",
        ([row["id"] for row in pools],),
    )
    cohorts = [row["payload"] for row in cursor]
    return FrozenComponent(
        schema_id="population/v1",
        data={
            "population.definitions": definitions,
            "population.pools": pools,
            "population.cohorts": cohorts,
            "population.materialized_people": read_scoped_rows(
                cursor, scope, "population.materialized_people"
            ),
            "population.lifecycle_transitions": read_scoped_rows(
                cursor, scope, "population.lifecycle_transitions"
            ),
        },
    )


def collect_checkpoint(
    cursor: RealDictCursor, hold: CheckpointHold, artifacts_root: Path
) -> CampaignCheckpoint:
    scope = (str(hold.world_id), str(hold.branch_id))
    cursor.execute(
        "SELECT version,state,state_hash FROM sim.branch_projections "
        "WHERE (world_id,branch_id)=(%s,%s)",
        scope,
    )
    projection = cursor.fetchone()
    if projection is None or (projection["version"], projection["state_hash"]) != (
        hold.projection_version,
        hold.state_hash,
    ):
        raise CheckpointHoldConflict("projection changed after the checkpoint hold")
    projections = projection["state"]
    cursor.execute(
        "SELECT max(split_part(version,'_',1)::int) AS v FROM infra_meta.schema_migrations"
    )
    schema = cursor.fetchone()
    if schema is None or schema["v"] is None:
        raise ValueError("checkpoint schema version is unavailable")
    origin = None
    if schema["v"] >= 23:
        cursor.execute(
            "SELECT rule_id,source_event_id FROM sim.campaign_checkpoint_dispatches "
            "WHERE (world_id,branch_id,request_id)=(%s,%s,%s)",
            (*scope, str(hold.request_id)),
        )
        origin = cursor.fetchone()
    boundary = CheckpointBoundary(
        world_id=hold.world_id,
        branch_id=hold.branch_id,
        continuation_epoch=0,
        capture_request_id=hold.request_id,
        trigger_event_id=origin["source_event_id"] if origin else None,
        trigger_schedule_id=origin["rule_id"] if origin else None,
        schema_version=schema["v"],
        projection_version=hold.projection_version,
        state_hash=hold.state_hash,
        command_ordinal=hold.command_ordinal,
        through_event_seq=hold.through_event_seq,
        through_event_id=hold.through_event_id,
        simulated_seconds=hold.simulated_seconds,
    )
    events = read_scoped_rows(cursor, scope, "sim.events", order=("seq_id",))
    commands = read_scoped_rows(cursor, scope, "sim.command_log", order=("seq_id",))
    last_event = (events[-1]["seq_id"], events[-1]["event_id"]) if events else (0, None)
    expected_event = (
        hold.through_event_seq,
        str(hold.through_event_id) if hold.through_event_id else None,
    )
    if last_event != expected_event or len(commands) != hold.command_ordinal:
        raise CheckpointHoldConflict("ledger changed after the checkpoint hold")
    event_refs: tuple[CheckpointReference, ...] = ()
    if events:
        perceptions = read_scoped_rows(
            cursor, scope, "sim.event_perceptions", order=("event_id", "observer_entity_id")
        )
        event_refs = (
            CheckpointReference(
                kind="physical-evidence-prefix",
                identity=f"{hold.branch_id}:{hold.through_event_seq}",
                version="v1",
                digest=stable_hash(
                    {"events": events, "commands": commands, "perceptions": perceptions}
                ),
            ),
        )

    minds = frozen_tables(
        cursor,
        scope,
        "minds/v1",
        "cognition.mind_states",
        "cognition.observations",
        "cognition.beliefs",
        "cognition.belief_evidence",
        "cognition.memories",
        "cognition.relationships",
        "cognition.relationship_changes",
    )
    rebuild_inputs = event_refs + (
        CheckpointReference(
            kind="snapshot-minds",
            identity=str(hold.request_id),
            version=minds.schema_id,
            digest=stable_hash(minds.data),
        ),
    )
    pending_work = {
        "sim.schedules": read_scoped_rows(cursor, scope, "sim.schedules"),
        "sim.world_due_work": read_scoped_rows(
            cursor, scope, "sim.world_due_work", omit=("lease_token", "lease_until", "attempts")
        ),
        "sim.interactions": read_scoped_rows(cursor, scope, "sim.interactions"),
    }
    if schema["v"] >= 23:
        pending_work["sim.campaign_checkpoint_rules"] = read_scoped_rows(
            cursor, scope, "sim.campaign_checkpoint_rules"
        )
    work = FrozenComponent(
        schema_id="pending-work/v1", data=cast(dict[str, JsonValue], pending_work)
    )
    time: dict[str, JsonValue] = {"seconds": hold.simulated_seconds}
    for key in ("tabletop.clock", "tabletop.activities", "tabletop.routines"):
        time[key] = projections.get(key, {})
    cursor.execute("SELECT domain_packs,settings FROM sim.worlds WHERE id=%s", (scope[0],))
    world_settings = cursor.fetchone()
    if world_settings is None:
        raise ValueError("checkpoint world settings are unavailable")
    time["world_settings"] = dict(world_settings)
    return CampaignCheckpoint(
        boundary=boundary,
        projections=projections,
        entities=read_snapshot_entities(cursor, hold.world_id, hold.branch_id),
        sections={
            CheckpointSection.PHYSICAL_EVIDENCE: PinnedComponent(
                schema_id="physical-evidence/v1", references=event_refs
            ),
            CheckpointSection.MINDS: minds,
            CheckpointSection.POPULATION: collect_population(cursor, scope),
            CheckpointSection.CHARACTER_RUNTIME: frozen_tables(
                cursor,
                scope,
                "character-runtime/v1",
                "tabletop.character_bindings",
                "persona.entity_assignments",
                "cognition.runtime_assignments",
                "cognition.controller_assignments",
                "cognition.controller_handoffs",
                "cognition.character_proposal_receipts",
                "cognition.decision_traces",
                "cognition.human_movement_evidence",
                "cognition.human_choice_evidence",
            ),
            CheckpointSection.ACTIVITIES_AND_CLOCK: FrozenComponent(schema_id="time/v1", data=time),
            CheckpointSection.RANDOMNESS: FrozenComponent(
                schema_id="randomness/v1",
                data={
                    "allocation_version": "logical-action-rng-1.0.0",
                    "command_ordinal": hold.command_ordinal,
                    "runs": read_scoped_rows(cursor, scope, "sim.runs", omit=("model_assignment",)),
                },
            ),
            CheckpointSection.PENDING_WORK: work,
            CheckpointSection.STORY: AbsentComponent(
                schema_id="story/v1", reason="STORY_NOT_INSTALLED"
            ),
            CheckpointSection.NARRATION: RebuildComponent(
                schema_id="narration/v1",
                builder_version=NARRATION_VERSION,
                references=rebuild_inputs,
            ),
            CheckpointSection.RETRIEVAL: RebuildComponent(
                schema_id="retrieval/v1",
                builder_version=KNOWLEDGE_VERSION,
                references=rebuild_inputs,
            ),
            CheckpointSection.VERSIONED_ARTIFACTS: pin_artifacts(cursor, scope, artifacts_root),
        },
    )


def lock_checkpoint_archives(
    cursor: RealDictCursor, world: uuid.UUID, branch: uuid.UUID, *, shared: bool
) -> None:
    key = f"tabletop:checkpoint-archives:{world}:{branch}"
    statement = (
        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))"
        if shared
        else "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))"
    )
    cursor.execute(statement, (key,))


def checkpoint_retired(
    cursor: RealDictCursor, world: uuid.UUID, branch: uuid.UUID, checkpoint: uuid.UUID
) -> bool:
    cursor.execute("SELECT to_regclass('sim.campaign_checkpoint_retention_state') AS state_table")
    version = cursor.fetchone()
    if version is None or version["state_table"] is None:
        return False
    cursor.execute(
        "SELECT 1 FROM sim.campaign_checkpoint_retention_state "
        "WHERE (world_id,branch_id,checkpoint_id)=(%s,%s,%s) AND status='RETIRED'",
        (str(world), str(branch), str(checkpoint)),
    )
    return cursor.fetchone() is not None


class PostgresCampaignCheckpoints:
    """Manager-only capture and integrity-checked loading at one held boundary."""

    def __init__(self, dsn: str, root: Path, holds: PostgresCheckpointHolds) -> None:
        self.dsn = dsn
        self.store = CampaignCheckpointStore(root)
        self.holds = holds

    def _load_verified(self, manifest: CampaignCheckpointManifest) -> CampaignCheckpoint:
        try:
            return self.store.load(manifest)
        except (OSError, ValueError, EOFError):
            raise CheckpointHoldConflict("checkpoint archive could not be verified") from None

    def capture(
        self,
        world: uuid.UUID,
        branch: uuid.UUID,
        request: uuid.UUID,
        actor: uuid.UUID,
        label: str,
    ) -> CheckpointReceipt:
        try:
            return self._capture_once(world, branch, request, actor, label)
        except (psycopg2.errors.SerializationFailure, psycopg2.errors.UniqueViolation):
            # Another writer may have published the same request while our snapshot waited.
            return self._capture_once(world, branch, request, actor, label)

    def _capture_once(
        self,
        world: uuid.UUID,
        branch: uuid.UUID,
        request: uuid.UUID,
        actor: uuid.UUID,
        label: str,
    ) -> CheckpointReceipt:
        scope = (str(world), str(branch), str(request))
        with transaction(actor_id=actor, dsn=self.dsn, isolation="REPEATABLE READ") as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL TIME ZONE 'UTC'")
                self.holds.authorize(cursor, world, actor, private=True)
                cursor.execute(
                    "SELECT label,manifest,created_at FROM sim.campaign_checkpoints "
                    "WHERE (world_id,branch_id,request_id)=(%s,%s,%s)",
                    scope,
                )
                prior = cursor.fetchone()
                if prior is not None:
                    receipt = CheckpointReceipt.model_validate(prior)
                    if receipt.label != label:
                        raise CheckpointHoldConflict(
                            "checkpoint request already has a different label"
                        )
                    return receipt
                held = self.holds.lock_for_capture(cursor, world, branch, request)
                if held.status != "READY":
                    raise CheckpointHoldConflict(
                        "checkpoint requires a held and projected event prefix"
                    )
                checkpoint = collect_checkpoint(cursor, held.hold, self.store.root.parent)
                try:
                    manifest = self.store.create(checkpoint)
                except OSError:
                    raise CheckpointHoldConflict(
                        "checkpoint archive could not be written"
                    ) from None
                try:
                    cursor.execute(
                        "INSERT INTO sim.campaign_checkpoints "
                        "(world_id,branch_id,request_id,checkpoint_id,actor_id,label,manifest) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING label,manifest,created_at",
                        (
                            *scope,
                            str(manifest.checkpoint_id),
                            str(actor),
                            label,
                            manifest.model_dump_json(),
                        ),
                    )
                except psycopg2.errors.InsufficientPrivilege:
                    raise CheckpointHoldConflict(
                        "checkpoint scope changed before publication"
                    ) from None
                return CheckpointReceipt.model_validate(cursor.fetchone())

    def load(
        self, world: uuid.UUID, branch: uuid.UUID, checkpoint_id: uuid.UUID, actor: uuid.UUID
    ) -> tuple[CheckpointReceipt, CampaignCheckpoint]:
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.holds.authorize(cursor, world, actor, private=True)
                lock_checkpoint_archives(cursor, world, branch, shared=True)
                if checkpoint_retired(cursor, world, branch, checkpoint_id):
                    raise CheckpointHoldConflict("checkpoint archive was retired by policy")
                cursor.execute(
                    "SELECT label,manifest,created_at FROM sim.campaign_checkpoints "
                    "WHERE (world_id,branch_id,checkpoint_id)=(%s,%s,%s)",
                    (str(world), str(branch), str(checkpoint_id)),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(checkpoint_id)
                receipt = CheckpointReceipt.model_validate(row)
                return receipt, self._load_verified(receipt.manifest)
