from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from psycopg2.extras import RealDictCursor
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from kernel.campaign_checkpoints import CampaignCheckpointManifest
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.database import after_commit, transaction
from kernel.postgres_campaign_checkpoints import (
    PostgresCampaignCheckpoints,
    checkpoint_retired,
    lock_checkpoint_archives,
)


class RetentionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: uuid.UUID
    keep_automatic: int | None = Field(ge=1, le=1000)


class RetentionRequest(RetentionSettings):
    expected_policy_id: uuid.UUID | None = None


class CheckpointRetentionPolicy(RetentionSettings):
    revision: int
    created_at: AwareDatetime


class CheckpointPinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pinned: bool = Field(strict=True)


class CheckpointPin(BaseModel):
    model_config = ConfigDict(frozen=True)

    checkpoint_id: uuid.UUID
    status: Literal["AVAILABLE", "PINNED"]


class ApplyRetentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: uuid.UUID


class RetentionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    retired_checkpoint_ids: tuple[uuid.UUID, ...]
    cleanup_pending: int


class PostgresCheckpointRetention:
    """Policy and archive lifecycle serialize independently of gameplay writes."""

    def __init__(self, archives: PostgresCampaignCheckpoints) -> None:
        self.archives = archives

    @contextmanager
    def _scope(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, *, write: bool = False
    ) -> Iterator[RealDictCursor]:
        with transaction(actor_id=actor, dsn=self.archives.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.archives.holds.authorize(cursor, world, actor, private=True)
                lock_checkpoint_archives(cursor, world, branch, shared=not write)
                self.archives.holds._require_branch(cursor, world, branch, lock=write)
                yield cursor

    @staticmethod
    def _current(
        cursor: RealDictCursor, scope: tuple[str, str]
    ) -> CheckpointRetentionPolicy | None:
        cursor.execute(
            "SELECT policy_id,keep_automatic,revision,created_at "
            "FROM sim.campaign_checkpoint_retention "
            "WHERE (world_id,branch_id)=(%s,%s) ORDER BY revision DESC LIMIT 1",
            scope,
        )
        row = cursor.fetchone()
        return CheckpointRetentionPolicy.model_validate(row) if row is not None else None

    def read(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointRetentionPolicy | None:
        with self._scope(world, branch, actor) as cursor:
            return self._current(cursor, (str(world), str(branch)))

    def configure(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request: RetentionRequest
    ) -> CheckpointRetentionPolicy:
        scope = (str(world), str(branch))
        with self._scope(world, branch, actor, write=True) as cursor:
            cursor.execute(
                "SELECT policy_id,keep_automatic,revision,created_at,actor_id "
                "FROM sim.campaign_checkpoint_retention "
                "WHERE (world_id,branch_id,policy_id)=(%s,%s,%s)",
                (*scope, str(request.policy_id)),
            )
            prior = cursor.fetchone()
            if prior is not None:
                if (prior.pop("actor_id"), prior["keep_automatic"]) != (
                    str(actor),
                    request.keep_automatic,
                ):
                    raise CheckpointHoldConflict("checkpoint retention identifier was already used")
                return CheckpointRetentionPolicy.model_validate(prior)
            current = self._current(cursor, scope)
            if (current.policy_id if current else None) != request.expected_policy_id:
                raise CheckpointHoldConflict("the checkpoint retention policy changed")
            cursor.execute(
                "INSERT INTO sim.campaign_checkpoint_retention "
                "(world_id,branch_id,policy_id,revision,actor_id,keep_automatic) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING "
                "policy_id,keep_automatic,revision,created_at",
                (
                    *scope,
                    str(request.policy_id),
                    current.revision + 1 if current else 1,
                    str(actor),
                    request.keep_automatic,
                ),
            )
            return CheckpointRetentionPolicy.model_validate(cursor.fetchone())

    def pin(
        self,
        world: uuid.UUID,
        branch: uuid.UUID,
        checkpoint: uuid.UUID,
        actor: uuid.UUID,
        request: CheckpointPinRequest,
    ) -> CheckpointPin:
        scope = (str(world), str(branch), str(checkpoint))
        with self._scope(world, branch, actor, write=True) as cursor:
            cursor.execute(
                "SELECT 1 FROM sim.campaign_checkpoints "
                "WHERE (world_id,branch_id,checkpoint_id)=(%s,%s,%s)",
                scope,
            )
            if cursor.fetchone() is None:
                raise KeyError(checkpoint)
            if checkpoint_retired(cursor, world, branch, checkpoint):
                raise CheckpointHoldConflict("checkpoint archive was retired by policy")
            cursor.execute(
                "INSERT INTO sim.campaign_checkpoint_retention_state AS state "
                "(world_id,branch_id,checkpoint_id,actor_id,status) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (world_id,branch_id,checkpoint_id) DO UPDATE "
                "SET actor_id=excluded.actor_id,status=excluded.status,"
                "changed_at=clock_timestamp() "
                "WHERE state.status <> 'RETIRED' RETURNING checkpoint_id,status",
                (*scope, str(actor), "PINNED" if request.pinned else "AVAILABLE"),
            )
            row = cursor.fetchone()
            if row is None:
                raise CheckpointHoldConflict("checkpoint archive was retired by policy")
            return CheckpointPin.model_validate(row)

    def _retire(
        self,
        cursor: RealDictCursor,
        scope: tuple[str, str],
        actor: uuid.UUID,
        policy: CheckpointRetentionPolicy,
    ) -> tuple[uuid.UUID, ...]:
        if policy.keep_automatic is None:
            return ()
        cursor.execute(
            """SELECT c.manifest,s.status FROM sim.campaign_checkpoints c
               JOIN sim.campaign_checkpoint_dispatches AS d USING (world_id,branch_id,request_id)
               JOIN sim.campaign_checkpoint_holds AS h USING (world_id,branch_id,request_id)
               LEFT JOIN sim.campaign_checkpoint_retention_state AS s
                 USING (world_id,branch_id,checkpoint_id)
               WHERE (c.world_id,c.branch_id)=(%s,%s) AND h.released_at IS NOT NULL
                 AND s.status IS DISTINCT FROM 'RETIRED'
               ORDER BY h.through_event_seq DESC,c.created_at DESC,c.checkpoint_id DESC""",
            scope,
        )
        rows = cursor.fetchall()
        candidates = [
            CampaignCheckpointManifest.model_validate(row["manifest"])
            for row in rows[policy.keep_automatic :]
            if row["status"] != "PINNED"
        ]
        if not candidates:
            return ()
        for row in rows[: policy.keep_automatic]:
            manifest = CampaignCheckpointManifest.model_validate(row["manifest"])
            self.archives.load_verified_at_cut(cursor, manifest)
        for manifest in candidates:
            cursor.execute(
                "INSERT INTO sim.campaign_checkpoint_retention_state "
                "(world_id,branch_id,checkpoint_id,actor_id,status,policy_id) "
                "VALUES (%s,%s,%s,%s,'RETIRED',%s) "
                "ON CONFLICT (world_id,branch_id,checkpoint_id) DO UPDATE "
                "SET actor_id=excluded.actor_id,status=excluded.status,"
                "policy_id=excluded.policy_id,changed_at=clock_timestamp()",
                (*scope, str(manifest.checkpoint_id), str(actor), str(policy.policy_id)),
            )
        return tuple(manifest.checkpoint_id for manifest in candidates)

    def apply(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID, request: ApplyRetentionRequest
    ) -> RetentionResult:
        scope = (str(world), str(branch))
        with self._scope(world, branch, actor, write=True) as cursor:
            current = self._current(cursor, scope)
            if current is None or current.policy_id != request.policy_id:
                raise CheckpointHoldConflict("the checkpoint retention policy changed")
            retired = self._retire(cursor, scope, actor, current)
            cursor.execute(
                """SELECT c.manifest FROM sim.campaign_checkpoints c
                   JOIN sim.campaign_checkpoint_retention_state s
                     USING (world_id,branch_id,checkpoint_id)
                   WHERE (c.world_id,c.branch_id)=(%s,%s) AND s.status='RETIRED'""",
                scope,
            )
            cleanup = tuple(
                CampaignCheckpointManifest.model_validate(row["manifest"]) for row in cursor
            )
        pending = (
            len(cleanup) if after_commit(lambda: self._cleanup(cleanup)) else self._cleanup(cleanup)
        )
        return RetentionResult(retired_checkpoint_ids=retired, cleanup_pending=pending)

    def _cleanup(self, manifests: tuple[CampaignCheckpointManifest, ...]) -> int:
        pending = 0
        for manifest in manifests:
            try:
                self.archives.store.remove_retired(manifest)
            except OSError:
                pending += 1
        return pending
