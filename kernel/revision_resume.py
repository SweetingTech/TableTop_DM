from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

import psycopg2.errors
from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime, Field

from domains.tabletop.world_time import CLOCK, Clock, ConfigureRequest
from kernel.campaign_checkpoints import (
    CampaignCheckpointManifest,
    CheckpointModel,
    CheckpointSection,
)
from kernel.campaign_revisions import PostgresCampaignRevisions, restored_run_id, revision_operator
from kernel.checkpoint_holds import CheckpointHoldConflict, require_checkpoint_open
from kernel.checkpoint_knowledge import archived_rows
from kernel.command_bus import CommandDefinition
from kernel.contracts import Actor, CommandProposal
from kernel.control import ControllerState, ControlMode, persist_controller
from kernel.database import unit_of_work
from kernel.postgres_campaign_checkpoints import PostgresCampaignCheckpoints
from kernel.postgres_repository import PostgresCommandRepository
from kernel.revision_activation import CommittedRevision, PostgresRevisionActivation


class ResumeCampaignRevision(CheckpointModel):
    request_id: uuid.UUID
    expected_epoch: int = Field(ge=1, le=2**63 - 1)
    run_clock: bool = True


class CampaignResumeReceipt(CheckpointModel):
    world_id: uuid.UUID
    source_branch_id: uuid.UUID
    revision_request_id: uuid.UUID
    request_id: uuid.UUID
    actor_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    epoch: int
    run_clock: bool
    clock_event_id: uuid.UUID | None
    human_controllers: int
    autonomous_controllers: int
    paused_controllers: int
    resumed_at: AwareDatetime


class PostgresRevisionResume:
    def __init__(
        self,
        archives: PostgresCampaignCheckpoints,
        commands: PostgresCommandRepository,
        clock_definition: CommandDefinition,
    ) -> None:
        self.archives = archives
        self.revisions = PostgresCampaignRevisions(archives)
        self.commands = commands
        self.clock_definition = clock_definition

    @staticmethod
    def _lock_continuation(cursor: RealDictCursor, committed: CommittedRevision) -> dict:
        scope = (str(committed.world_id), str(committed.branch_id))
        cursor.execute(
            "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE",
            scope,
        )
        if cursor.fetchone() is None:
            raise CheckpointHoldConflict("restored branch is unavailable")
        cursor.execute(
            """SELECT p.state FROM sim.branch_projections p
               JOIN sim.campaign_continuations h
                 ON (h.world_id,h.branch_id)=(p.world_id,p.branch_id)
               JOIN sim.runs r ON (r.world_id,r.branch_id)=(p.world_id,p.branch_id)
               WHERE (p.world_id,p.branch_id)=(%s,%s) AND h.epoch=%s
                 AND r.id=%s AND r.run_kind='LIVE' AND r.status='PAUSED'""",
            (*scope, committed.epoch, str(committed.run_id)),
        )
        row = cursor.fetchone()
        if row is None:
            raise CheckpointHoldConflict("this revision does not own the paused continuation")
        require_checkpoint_open(cursor, committed.world_id, committed.branch_id)
        return dict(row["state"])

    def _archived_modes(
        self, cursor: RealDictCursor, committed: CommittedRevision
    ) -> dict[tuple[uuid.UUID, uuid.UUID], ControlMode]:
        cursor.execute(
            """SELECT ar.manifest FROM sim.campaign_checkpoints ar
               JOIN sim.campaign_revision_plans p ON
                (p.world_id,p.branch_id,p.source_checkpoint_id)=(ar.world_id,ar.branch_id,ar.checkpoint_id)
               WHERE (p.world_id,p.branch_id,p.request_id)=(%s,%s,%s)
                 AND p.source_archive_hash=ar.manifest->>'artifact_hash'""",
            (str(committed.world_id), str(committed.source_branch_id), str(committed.request_id)),
        )
        row = cursor.fetchone()
        if row is None:
            raise CheckpointHoldConflict("revision checkpoint is unavailable for resume")
        manifest = CampaignCheckpointManifest.model_validate(row["manifest"])
        checkpoint, _ = self.archives.load_verified_at_cut(cursor, manifest)
        modes = {}
        for state in archived_rows(
            checkpoint, CheckpointSection.CHARACTER_RUNTIME, "cognition.controller_assignments"
        ):
            saved = ControllerState.model_validate(state["payload"])
            modes[(restored_run_id(committed.branch_id, saved.run_id), saved.entity_id)] = (
                saved.mode
            )
        return modes

    @staticmethod
    def _authorized_controller_mode(
        cursor: RealDictCursor, state: ControllerState, owner: str | None, desired: ControlMode
    ) -> ControlMode:
        if desired == "PAUSED":
            return "PAUSED"
        actor = state.owner_actor_id if desired == "HUMAN" else state.executor_actor_id
        required = (
            {"entity.act"}
            if desired == "HUMAN"
            else {"world.read", "action.propose", "action.commit", "entity.act"}
        )
        if desired == "HUMAN" and str(actor) != owner:
            return "PAUSED"
        if desired == "AUTONOMOUS" and state.step >= state.max_steps:
            return "PAUSED"
        cursor.execute(
            """SELECT c.capability,a.actor_kind FROM sim.actor_capabilities c
               JOIN sim.actors a ON a.id=c.actor_id AND a.is_active
               WHERE (c.world_id,c.actor_id)=(%s,%s) AND c.capability=ANY(%s::text[])
               FOR SHARE OF c,a""",
            (str(state.world_id), str(actor), sorted(required)),
        )
        granted = cursor.fetchall()
        if {row["capability"] for row in granted} != required:
            return "PAUSED"
        if desired == "AUTONOMOUS" and granted[0]["actor_kind"] != "AGENT":
            return "PAUSED"
        return desired

    def _resume_controllers(
        self, cursor: RealDictCursor, committed: CommittedRevision, now: datetime
    ) -> Counter[ControlMode]:
        modes = self._archived_modes(cursor, committed)
        counts: Counter[ControlMode] = Counter()
        cursor.execute(
            """SELECT c.payload,e.controller_actor_id FROM cognition.controller_assignments c
               JOIN sim.entities e
                 ON (e.world_id,e.branch_id,e.id)=(c.world_id,c.branch_id,c.entity_id)
               WHERE (c.world_id,c.branch_id,c.run_id)=(%s,%s,%s)
               ORDER BY c.entity_id FOR UPDATE OF c""",
            (str(committed.world_id), str(committed.branch_id), str(committed.run_id)),
        )
        for row in cursor.fetchall():
            current = ControllerState.model_validate(row["payload"])
            if current.epoch != 1 or current.mode != "PAUSED":
                counts[current.mode] += 1
                continue
            mode = self._authorized_controller_mode(
                cursor,
                current,
                row["controller_actor_id"],
                modes.get((current.run_id, current.entity_id), "PAUSED"),
            )
            counts[mode] += 1
            if mode == "PAUSED":
                continue
            presence = (
                now + timedelta(seconds=current.disconnect_after_seconds)
                if mode == "HUMAN" and current.disconnect_after_seconds is not None
                else None
            )
            persist_controller(
                cursor,
                current.model_copy(
                    update={
                        "mode": mode,
                        "epoch": current.epoch + 1,
                        "next_due": now,
                        "presence_deadline_at": presence,
                    }
                ),
            )
        return counts

    def _resume_clock(
        self,
        committed: CommittedRevision,
        actor: Actor,
        request: ResumeCampaignRevision,
        raw: dict | None,
        now: datetime,
    ) -> uuid.UUID | None:
        if not request.run_clock or raw is None:
            return None
        clock = Clock.model_validate(raw)
        if clock.run_id != committed.run_id:
            raise CheckpointHoldConflict("the restored run does not own this clock")
        if not clock.paused:
            return None
        setup = ConfigureRequest(
            expected_epoch=clock.epoch,
            executor_actor_id=clock.executor_actor_id,
            paused=False,
            seconds_per_tick=clock.seconds_per_tick,
            offline_policy=clock.offline_policy,
            max_catch_up_ticks=clock.max_catch_up_ticks,
            until_seconds=(
                clock.until_seconds
                if clock.until_seconds is not None and clock.until_seconds > clock.seconds
                else None
            ),
            wall_time=now,
        )
        proposal = CommandProposal(
            world_id=committed.world_id,
            branch_id=committed.branch_id,
            run_id=committed.run_id,
            actor_id=actor.actor_id,
            command_type=self.clock_definition.command_type,
            parameters=setup.model_dump(mode="json"),
            input_origin="OPERATOR",
            idempotency_key=f"campaign-resume:{request.request_id}",
        )
        receipt = self.commands.execute(proposal, actor, self.clock_definition)
        if receipt.event.event_type != self.clock_definition.command_type:
            raise CheckpointHoldConflict("the resume clock request key was previously used")
        return receipt.event.event_id

    def resume(
        self,
        world: uuid.UUID,
        source_branch: uuid.UUID,
        actor_id: uuid.UUID,
        revision_id: uuid.UUID,
        request: ResumeCampaignRevision,
    ) -> CampaignResumeReceipt:
        try:
            return self._resume_once(world, source_branch, actor_id, revision_id, request)
        except psycopg2.errors.InsufficientPrivilege:
            raise PermissionError("campaign resume requires current operator authority") from None
        except psycopg2.errors.IntegrityError:
            raise CheckpointHoldConflict("campaign resume failed durable validation") from None

    def _resume_once(
        self,
        world: uuid.UUID,
        source_branch: uuid.UUID,
        actor_id: uuid.UUID,
        revision_id: uuid.UUID,
        request: ResumeCampaignRevision,
    ) -> CampaignResumeReceipt:
        scope = (str(world), str(source_branch), str(revision_id))
        with unit_of_work(actor_id=actor_id, dsn=self.archives.dsn):
            with self.revisions._scope(world, source_branch, actor_id, write=True) as cursor:
                actor = revision_operator(cursor, world, actor_id, "resume")
                cursor.execute(
                    "SELECT * FROM sim.campaign_revision_resumes "
                    "WHERE (world_id,source_branch_id,revision_request_id)=(%s,%s,%s)",
                    scope,
                )
                previous = cursor.fetchone()
                if previous is not None:
                    receipt = CampaignResumeReceipt.model_validate(previous)
                    if (receipt.request_id, receipt.actor_id, receipt.epoch, receipt.run_clock) != (
                        request.request_id,
                        actor_id,
                        request.expected_epoch,
                        request.run_clock,
                    ):
                        raise CheckpointHoldConflict("campaign revision was already resumed")
                    return receipt
                committed = PostgresRevisionActivation._receipt(cursor, scope)
                if committed is None or committed.epoch != request.expected_epoch:
                    raise CheckpointHoldConflict("campaign revision is uncommitted or stale")
                projection = self._lock_continuation(cursor, committed)
                now = datetime.now(UTC)
                counts = self._resume_controllers(cursor, committed, now)
                clock_event = self._resume_clock(
                    committed, actor, request, projection.get(CLOCK, {}).get("singleton"), now
                )
                cursor.execute(
                    "UPDATE sim.runs SET status='RUNNING',"
                    "started_at=COALESCE(started_at,clock_timestamp()) "
                    "WHERE (world_id,branch_id,id)=(%s,%s,%s) AND status='PAUSED'",
                    (str(world), str(committed.branch_id), str(committed.run_id)),
                )
                cursor.execute(
                    """INSERT INTO sim.campaign_revision_resumes
                       (world_id,source_branch_id,revision_request_id,request_id,actor_id,
                        branch_id,run_id,epoch,run_clock,clock_event_id,
                        human_controllers,autonomous_controllers,paused_controllers)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        *scope,
                        str(request.request_id),
                        str(actor_id),
                        str(committed.branch_id),
                        str(committed.run_id),
                        committed.epoch,
                        request.run_clock,
                        str(clock_event) if clock_event else None,
                        counts["HUMAN"],
                        counts["AUTONOMOUS"],
                        counts["PAUSED"],
                    ),
                )
                return CampaignResumeReceipt.model_validate(cursor.fetchone())
