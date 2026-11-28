from __future__ import annotations

import uuid
from typing import Literal

import psycopg2.errors
from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime, Field

from kernel.campaign_checkpoints import CampaignCheckpointManifest, CheckpointModel, Digest
from kernel.campaign_revisions import (
    CampaignRevisionPlan,
    PlannedCorrection,
    PostgresCampaignRevisions,
    revision_hold_id,
    revision_operator,
)
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.command_bus import CommandDefinition
from kernel.contracts import CommandProposal
from kernel.database import unit_of_work
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints, checkpoint_retired
from kernel.postgres_control_plane import PostgresControlPlane
from kernel.postgres_repository import PostgresCommandRepository
from kernel.revision_restore import RestoredCampaign, persist_restored_campaign
from kernel.snapshots import SnapshotStore
from kernel.state import stable_hash

CORRECTION_KEY_PREFIX = "campaign-revision-correction:"


class CommittedCorrection(CheckpointModel):
    event_id: uuid.UUID
    state_hash: Digest


class CommittedRevision(CheckpointModel):
    world_id: uuid.UUID
    source_branch_id: uuid.UUID
    request_id: uuid.UUID
    actor_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    epoch: int
    state_hash: Digest
    committed_at: AwareDatetime
    correction: CommittedCorrection | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class RevisionActivation(CheckpointModel):
    phase: Literal["DRAINING", "COMMITTED"]
    request_id: uuid.UUID
    pending_events: int = 0
    receipt: CommittedRevision | None = None


class PostgresRevisionActivation:
    def __init__(
        self,
        archives: PostgresCampaignCheckpoints,
        control: PostgresControlPlane,
        snapshots: SnapshotStore,
        commands: PostgresCommandRepository,
        correction_definition: CommandDefinition,
    ) -> None:
        self.archives = archives
        self.revisions = PostgresCampaignRevisions(archives)
        self.control = control
        self.snapshots = snapshots
        self.commands = commands
        self.correction_definition = correction_definition

    @staticmethod
    def _receipt(cursor: RealDictCursor, scope: tuple[str, str, str]) -> CommittedRevision | None:
        cursor.execute(
            """SELECT c.world_id,c.source_branch_id,c.request_id,c.actor_id,c.branch_id,c.run_id,
                      c.epoch,c.state_hash,c.committed_at,
                      CASE WHEN e.event_id IS NOT NULL THEN jsonb_build_object(
                        'event_id',e.event_id,'state_hash',l.resulting_state_hash) END AS correction
               FROM sim.campaign_revision_commits c
               JOIN sim.campaign_revision_plans p
                 ON (p.world_id,p.branch_id,p.request_id)=
                    (c.world_id,c.source_branch_id,c.request_id)
               LEFT JOIN sim.command_log l
                 ON (l.world_id,l.branch_id,l.run_id,l.actor_id)=
                    (c.world_id,c.branch_id,c.run_id,c.actor_id)
                 AND l.command_type='tabletop.timeline.correct'
                 AND l.idempotency_key=%s || c.request_id::text
                 AND l.parameters=p.provenance->'planned_correction'->'request'
                 AND l.resulting_state_hash=
                     p.provenance->'planned_correction'->>'resulting_state_hash'
               LEFT JOIN sim.events e
                 ON (e.world_id,e.branch_id,e.run_id,e.actor_id,e.idempotency_key,e.event_type)=
                    (l.world_id,l.branch_id,l.run_id,l.actor_id,l.idempotency_key,l.command_type)
               WHERE (c.world_id,c.source_branch_id,c.request_id)=(%s,%s,%s)
                 AND c.committed_at IS NOT NULL""",
            (CORRECTION_KEY_PREFIX, *scope),
        )
        row = cursor.fetchone()
        return CommittedRevision.model_validate(row) if row is not None else None

    @staticmethod
    def _committed(receipt: CommittedRevision) -> RevisionActivation:
        return RevisionActivation(phase="COMMITTED", request_id=receipt.request_id, receipt=receipt)

    def activate(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request: uuid.UUID
    ) -> RevisionActivation:
        scope = (str(world), str(branch), str(request))
        with self.revisions._scope(world, branch, actor, write=True) as cursor:
            existing = self._receipt(cursor, scope)
            if existing is not None:
                return self._committed(existing)
            plan = self.revisions._read(cursor, scope)
            if plan is None:
                raise KeyError(request)
            if plan.actor_id != actor:
                raise PermissionError("only the plan operator can activate the campaign revision")
            if plan.cancelled_at is not None:
                raise CheckpointHoldConflict("campaign revision was cancelled")
            cursor.execute(
                "SELECT capability FROM sim.actor_capabilities WHERE (world_id,actor_id)=(%s,%s) "
                "AND capability IN ('entity.control','mind.write.all') FOR SHARE",
                (str(world), str(actor)),
            )
            if len(cursor.fetchall()) != 2:
                raise PermissionError("campaign restore requires current operator authority")
            hold = self.archives.holds.begin(world, branch, revision_hold_id(request), actor)
        if hold.status == "DRAINING":
            return RevisionActivation(
                phase="DRAINING", request_id=request, pending_events=hold.pending_events
            )
        if hold.status != "READY":
            raise CheckpointHoldConflict("the revision's live hold was released")
        try:
            return self._apply(world, branch, actor, request)
        except psycopg2.errors.InsufficientPrivilege:
            raise PermissionError("campaign restore requires current operator authority") from None
        except psycopg2.errors.IntegrityError:
            raise CheckpointHoldConflict("campaign revision failed durable validation") from None

    def _apply(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request: uuid.UUID
    ) -> RevisionActivation:
        scope = (str(world), str(branch), str(request))
        with (
            unit_of_work(actor_id=actor, dsn=self.archives.dsn),
            self.revisions._scope(world, branch, actor, write=True) as cursor,
        ):
            previous = self._receipt(cursor, scope)
            if previous is not None:
                return self._committed(previous)
            plan = self.revisions._read(cursor, scope)
            if plan is None or plan.cancelled_at is not None:
                raise CheckpointHoldConflict("campaign revision plan is unavailable")
            if checkpoint_retired(cursor, world, branch, plan.source_checkpoint_id):
                raise CheckpointHoldConflict("checkpoint archive was retired by policy")
            cursor.execute(
                "SELECT manifest FROM sim.campaign_checkpoints "
                "WHERE (world_id,branch_id,checkpoint_id)=(%s,%s,%s)",
                (str(world), str(branch), str(plan.source_checkpoint_id)),
            )
            row = cursor.fetchone()
            if row is None:
                raise CheckpointHoldConflict("revision checkpoint is unavailable")
            manifest = CampaignCheckpointManifest.model_validate(row["manifest"])
            if manifest.artifact_hash != plan.source_archive_hash:
                raise CheckpointHoldConflict("revision archive identity changed")
            checkpoint, evidence = self.archives.load_verified_at_cut(cursor, manifest)
            candidate = RestoredCampaign.build(checkpoint, evidence, plan)
            cursor.execute(
                "SELECT sim.start_campaign_revision(%s,%s,%s,%s,%s)",
                (*scope, str(revision_hold_id(request)), stable_hash(candidate.projection)),
            )
            persist_restored_campaign(cursor, candidate, self.control, self.snapshots)
            cursor.execute("SELECT sim.finish_campaign_revision(%s,%s,%s)", scope)
            if plan.provenance.planned_correction is not None:
                self._commit_correction(cursor, plan, plan.provenance.planned_correction)
            receipt = self._receipt(cursor, scope)
            if receipt is None:
                raise CheckpointHoldConflict("campaign revision receipt is unavailable")
            return self._committed(receipt)

    def _commit_correction(
        self, cursor: RealDictCursor, plan: CampaignRevisionPlan, correction: PlannedCorrection
    ) -> None:
        actor = revision_operator(cursor, plan.world_id, plan.actor_id, "restore")
        proposal = CommandProposal(
            command_id=uuid.uuid5(plan.successor_branch_id, "planned-timeline-correction"),
            world_id=plan.world_id,
            branch_id=plan.successor_branch_id,
            run_id=plan.successor_run_id,
            actor_id=plan.actor_id,
            command_type=self.correction_definition.command_type,
            parameters=correction.request.model_dump(mode="json"),
            input_origin="OPERATOR",
            idempotency_key=f"{CORRECTION_KEY_PREFIX}{plan.request_id}",
            correlation_id=plan.request_id,
        )
        receipt = self.commands.execute(proposal, actor, self.correction_definition)
        if not receipt.result.accepted or receipt.state_hash != correction.resulting_state_hash:
            raise CheckpointHoldConflict("prepared correction produced a different state")
