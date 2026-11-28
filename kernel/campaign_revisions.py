from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Annotated, Literal

from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime, Field, JsonValue, StringConstraints

from domains.tabletop.quests.contracts import QUESTS, Quest
from domains.tabletop.world_time import CLOCK, Clock
from kernel.campaign_checkpoints import (
    CampaignCheckpoint,
    CampaignCheckpointManifest,
    CheckpointModel,
    CheckpointSection,
    Digest,
    FrozenComponent,
)
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.contracts import RunKind
from kernel.database import transaction
from kernel.postgres_campaign_checkpoints import (
    CheckpointEvidence,
    PostgresCampaignCheckpoints,
    checkpoint_retired,
    lock_checkpoint_archives,
)
from kernel.state import stable_hash

SeedPolicy = Literal["REUSE_CHECKPOINT_SEED", "FRESH_SEED"]
RevisionReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


class PrepareCampaignRevision(CheckpointModel):
    request_id: uuid.UUID
    expected_epoch: int = Field(ge=0, le=2**63 - 2)
    source_checkpoint_id: uuid.UUID
    source_live_run_id: uuid.UUID | None = None
    reason: RevisionReason = Field(repr=False)
    seed_policy: SeedPolicy = "FRESH_SEED"


class RevisionProvenance(CheckpointModel):
    restore_version: Literal["campaign-restore-1.0.0"] = "campaign-restore-1.0.0"
    source_state_hash: Digest
    source_command_ordinal: int
    source_event_seq: int
    command_versions: tuple[str, ...]
    model_versions: tuple[str, ...]
    persona_versions: tuple[str, ...]
    policy_versions: tuple[str, ...]
    prompt_versions: tuple[str, ...]


class CampaignRevisionPlan(CheckpointModel):
    world_id: uuid.UUID
    branch_id: uuid.UUID
    request_id: uuid.UUID
    actor_id: uuid.UUID
    expected_epoch: int
    source_checkpoint_id: uuid.UUID
    source_archive_hash: Digest
    reason: RevisionReason = Field(repr=False)
    seed_policy: SeedPolicy
    seed: int
    source_live_run_id: uuid.UUID
    successor_branch_id: uuid.UUID
    successor_run_id: uuid.UUID
    candidate_state_hash: Digest
    provenance: RevisionProvenance
    created_at: AwareDatetime
    cancelled_at: AwareDatetime | None = None


class ArchivedRun(CheckpointModel):
    id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_kind: RunKind
    status: str
    seed: int | None


def archived_runs(checkpoint: CampaignCheckpoint) -> dict[uuid.UUID, ArchivedRun]:
    randomness = checkpoint.sections[CheckpointSection.RANDOMNESS]
    assert isinstance(randomness, FrozenComponent)
    rows = randomness.data.get("runs")
    if not isinstance(rows, list):
        raise CheckpointHoldConflict("checkpoint is missing its run inventory")
    runs: dict[uuid.UUID, ArchivedRun] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CheckpointHoldConflict("checkpoint has an invalid archived run")
        run = ArchivedRun.model_validate(row, extra="ignore")
        if (run.world_id, run.branch_id) != (
            checkpoint.boundary.world_id,
            checkpoint.boundary.branch_id,
        ) or run.id in runs:
            raise CheckpointHoldConflict("checkpoint contains a run outside its archived scope")
        runs[run.id] = run
    return runs


def restored_run_id(successor_branch: uuid.UUID, source_run: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(successor_branch, f"run:{source_run}")


def build_paused_projection(
    checkpoint: CampaignCheckpoint,
    successor_branch: uuid.UUID,
    runs: dict[uuid.UUID, ArchivedRun],
) -> dict[str, dict[str, JsonValue]]:
    """Preserve the archived facts and remap the named run references."""
    result = deepcopy(checkpoint.projections)
    clock = result.get(CLOCK, {}).get("singleton")
    if clock is not None:
        archived_clock = Clock.model_validate(clock)
        if archived_clock.run_id not in runs or (
            archived_clock.seconds != checkpoint.boundary.simulated_seconds
        ):
            raise CheckpointHoldConflict("checkpoint clock disagrees with its archived boundary")
        result[CLOCK]["singleton"] = archived_clock.model_copy(
            update={
                "paused": True,
                "epoch": archived_clock.epoch + 1,
                "step": 0,
                "run_id": restored_run_id(successor_branch, archived_clock.run_id),
            }
        ).model_dump(mode="json")
    for identity, raw in result.get(QUESTS, {}).items():
        quest = Quest.model_validate(raw)
        if str(quest.quest_id) != identity or quest.run_id not in runs:
            raise CheckpointHoldConflict("checkpoint quest disagrees with its archived scope")
        result[QUESTS][identity] = quest.model_copy(
            update={"run_id": restored_run_id(successor_branch, quest.run_id)}
        ).model_dump(mode="json")
    return result


def archived_live_run(
    checkpoint: CampaignCheckpoint,
    runs: dict[uuid.UUID, ArchivedRun],
    requested: uuid.UUID | None,
) -> ArchivedRun:
    live = {
        run.id: run
        for run in runs.values()
        if run.run_kind is RunKind.LIVE and run.status in {"QUEUED", "RUNNING", "PAUSED"}
    }
    raw_clock = checkpoint.projections.get(CLOCK, {}).get("singleton")
    if raw_clock is not None:
        clock = Clock.model_validate(raw_clock)
        if requested is not None and requested != clock.run_id:
            raise CheckpointHoldConflict("selected run does not own the archived world clock")
        requested = clock.run_id
    if requested is None and len(live) == 1:
        requested = next(iter(live))
    if requested is None or requested not in live:
        raise CheckpointHoldConflict("checkpoint requires a matching live run")
    return live[requested]


def revision_provenance(
    checkpoint: CampaignCheckpoint, evidence: CheckpointEvidence
) -> RevisionProvenance:
    def values(field: str) -> tuple[str, ...]:
        return tuple(sorted({str(row[field]) for row in evidence.events if row.get(field)}))

    return RevisionProvenance(
        source_state_hash=checkpoint.boundary.state_hash,
        source_command_ordinal=checkpoint.boundary.command_ordinal,
        source_event_seq=checkpoint.boundary.through_event_seq,
        command_versions=tuple(
            sorted({f"{row['command_type']}@{row['command_version']}" for row in evidence.commands})
        ),
        model_versions=values("model_version"),
        persona_versions=values("persona_version"),
        policy_versions=values("policy_version"),
        prompt_versions=values("prompt_contract_version"),
    )


class PostgresCampaignRevisions:
    def __init__(self, archives: PostgresCampaignCheckpoints) -> None:
        self.archives = archives

    @contextmanager
    def _scope(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, *, write: bool = False
    ) -> Iterator[RealDictCursor]:
        with transaction(actor_id=actor, dsn=self.archives.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.archives.holds.authorize(cursor, world, actor, private=True)
                cursor.execute(
                    "SELECT 1 FROM sim.actor_capabilities WHERE (world_id,actor_id)=(%s,%s) "
                    "AND capability='action.commit' FOR SHARE",
                    (str(world), str(actor)),
                )
                if cursor.fetchone() is None:
                    raise PermissionError("campaign revision requires canonical commit authority")
                if write:
                    lock_checkpoint_archives(cursor, world, branch, shared=False)
                yield cursor

    @staticmethod
    def _read(cursor: RealDictCursor, scope: tuple[str, str, str]) -> CampaignRevisionPlan | None:
        cursor.execute(
            "SELECT * FROM sim.campaign_revision_plans "
            "WHERE (world_id,branch_id,request_id)=(%s,%s,%s)",
            scope,
        )
        row = cursor.fetchone()
        return CampaignRevisionPlan.model_validate(row) if row is not None else None

    def read(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request_id: uuid.UUID
    ) -> CampaignRevisionPlan:
        with self._scope(world, branch, actor) as cursor:
            prior = self._read(cursor, (str(world), str(branch), str(request_id)))
            if prior is None:
                raise KeyError(request_id)
            return prior

    def prepare(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, body: PrepareCampaignRevision
    ) -> CampaignRevisionPlan:
        scope = (str(world), str(branch), str(body.request_id))
        with self._scope(world, branch, actor, write=True) as cursor:
            prior = self._read(cursor, scope)
            if prior is not None:
                if (
                    prior.actor_id != actor
                    or prior.expected_epoch != body.expected_epoch
                    or prior.source_checkpoint_id != body.source_checkpoint_id
                    or prior.reason != body.reason
                    or prior.seed_policy != body.seed_policy
                    or body.source_live_run_id not in (None, prior.source_live_run_id)
                ):
                    raise CheckpointHoldConflict("revision request identifier was already used")
                return prior
            self.archives.holds._require_branch(cursor, world, branch, lock=True)
            cursor.execute(
                "SELECT 1 FROM sim.campaign_continuations "
                "WHERE (world_id,branch_id,epoch)=(%s,%s,%s)",
                (*scope[:2], body.expected_epoch),
            )
            if cursor.fetchone() is None:
                raise CheckpointHoldConflict("the active continuation changed")
            if checkpoint_retired(cursor, world, branch, body.source_checkpoint_id):
                raise CheckpointHoldConflict("checkpoint archive was retired by policy")
            cursor.execute(
                "SELECT manifest FROM sim.campaign_checkpoints "
                "WHERE (world_id,branch_id,checkpoint_id)=(%s,%s,%s)",
                (*scope[:2], str(body.source_checkpoint_id)),
            )
            row = cursor.fetchone()
            if row is None:
                raise KeyError(body.source_checkpoint_id)
            manifest = CampaignCheckpointManifest.model_validate(row["manifest"])
            if manifest.boundary.continuation_epoch != body.expected_epoch:
                raise CheckpointHoldConflict("the source checkpoint belongs to a different epoch")
            checkpoint, evidence = self.archives.load_verified_at_cut(cursor, manifest)
            runs = archived_runs(checkpoint)
            live = archived_live_run(checkpoint, runs, body.source_live_run_id)
            successor = uuid.uuid5(branch, f"campaign-continuation:{body.request_id}")
            projection = build_paused_projection(checkpoint, successor, runs)
            seed = (
                (live.seed or 0)
                if body.seed_policy == "REUSE_CHECKPOINT_SEED"
                else (
                    int(stable_hash([manifest.artifact_hash, str(successor)])[:16], 16)
                    & (2**63 - 1)
                )
            )
            cursor.execute(
                """INSERT INTO sim.campaign_revision_plans
                   (world_id,branch_id,request_id,actor_id,expected_epoch,source_checkpoint_id,
                    source_archive_hash,reason,seed_policy,seed,source_live_run_id,
                    successor_branch_id,successor_run_id,candidate_state_hash,provenance)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   RETURNING *""",
                (
                    *scope,
                    str(actor),
                    body.expected_epoch,
                    str(body.source_checkpoint_id),
                    manifest.artifact_hash,
                    body.reason,
                    body.seed_policy,
                    seed,
                    str(live.id),
                    str(successor),
                    str(restored_run_id(successor, live.id)),
                    stable_hash(projection),
                    revision_provenance(checkpoint, evidence).model_dump_json(),
                ),
            )
            return CampaignRevisionPlan.model_validate(cursor.fetchone())

    def cancel(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request_id: uuid.UUID
    ) -> CampaignRevisionPlan:
        scope = (str(world), str(branch), str(request_id))
        with self._scope(world, branch, actor, write=True) as cursor:
            prior = self._read(cursor, scope)
            if prior is None:
                raise KeyError(request_id)
            if prior.actor_id != actor:
                raise PermissionError("only the plan operator can cancel the campaign revision")
            if prior.cancelled_at is not None:
                return prior
            cursor.execute(
                "UPDATE sim.campaign_revision_plans SET cancelled_at=clock_timestamp() "
                "WHERE (world_id,branch_id,request_id)=(%s,%s,%s) RETURNING *",
                scope,
            )
            return CampaignRevisionPlan.model_validate(cursor.fetchone())
