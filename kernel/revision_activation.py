from __future__ import annotations

import uuid
from typing import Literal

import psycopg2.errors
from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime

from kernel.campaign_activation import CampaignActivationFacts
from kernel.campaign_checkpoints import CampaignCheckpointManifest, CheckpointModel, Digest
from kernel.campaign_revisions import PostgresCampaignRevisions, revision_hold_id
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.command_bus import CommandDefinition
from kernel.contracts import Actor, ActorKind, CommandProposal
from kernel.database import unit_of_work
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints, checkpoint_retired
from kernel.postgres_control_plane import PostgresControlPlane
from kernel.postgres_repository import PostgresCommandRepository
from kernel.revision_restore import RestoredCampaign, persist_restored_campaign
from kernel.snapshots import SnapshotStore
from kernel.state import stable_hash


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
        activation_definition: CommandDefinition,
    ) -> None:
        self.archives = archives
        self.revisions = PostgresCampaignRevisions(archives)
        self.control = control
        self.snapshots = snapshots
        self.commands = commands
        self.activation_definition = activation_definition

    @staticmethod
    def _receipt(cursor: RealDictCursor, scope: tuple[str, str, str]) -> CommittedRevision | None:
        cursor.execute(
            """SELECT world_id,source_branch_id,request_id,actor_id,branch_id,run_id,
                      epoch,state_hash,committed_at
               FROM sim.campaign_revision_commits
               WHERE (world_id,source_branch_id,request_id)=(%s,%s,%s)
                 AND committed_at IS NOT NULL""",
            scope,
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
            facts = CampaignActivationFacts(
                source_branch_id=branch,
                source_checkpoint_id=plan.source_checkpoint_id,
                request_id=request,
                epoch=plan.expected_epoch + 1,
                state_hash=stable_hash(candidate.projection),
            )
            proposal = CommandProposal(
                command_id=uuid.uuid5(plan.successor_branch_id, "campaign-activation"),
                command_type=self.activation_definition.command_type,
                world_id=world,
                branch_id=plan.successor_branch_id,
                run_id=plan.successor_run_id,
                actor_id=actor,
                input_origin="OPERATOR",
                parameters=facts.model_dump(mode="json"),
                idempotency_key=f"campaign-activation:{request}",
                correlation_id=request,
                seed=plan.seed,
            )
            cursor.execute(
                "SELECT sim.start_campaign_revision(%s,%s,%s,%s,%s)",
                (*scope, str(revision_hold_id(request)), facts.state_hash),
            )
            persist_restored_campaign(cursor, candidate, self.control, self.snapshots)
            self._commit_activation(cursor, proposal)
            cursor.execute("SELECT sim.finish_campaign_revision(%s,%s,%s)", scope)
            receipt = self._receipt(cursor, scope)
            if receipt is None:
                raise CheckpointHoldConflict("campaign revision receipt is unavailable")
            return self._committed(receipt)

    def _commit_activation(self, cursor: RealDictCursor, proposal: CommandProposal) -> None:
        cursor.execute(
            "SELECT actor_kind,display_name FROM sim.actors WHERE id=%s AND is_active FOR SHARE",
            (str(proposal.actor_id),),
        )
        row = cursor.fetchone()
        if row is None:
            raise PermissionError("campaign activation requires an active operator")
        actor = Actor(
            actor_id=proposal.actor_id,
            kind=ActorKind(row["actor_kind"]),
            display_name=row["display_name"],
        )
        self.commands.execute(proposal, actor, self.activation_definition)
