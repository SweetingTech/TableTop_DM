from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from psycopg2.extensions import cursor as PgCursor
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, ConfigDict

from kernel.campaign_checkpoints import Digest
from kernel.contracts import BranchKind
from kernel.database import transaction
from kernel.errors import BranchCheckpointHeld, BranchIsolationError

if TYPE_CHECKING:
    from kernel.application import SimulationApplication

CHECKPOINT_AUTHORITY = frozenset({"run.branch", "world.read.all", "mind.read.all"})


class CheckpointHoldConflict(ValueError):
    """Another capture already owns the branch's quiescent boundary."""


class CheckpointHold(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: uuid.UUID
    branch_id: uuid.UUID
    request_id: uuid.UUID
    actor_id: uuid.UUID
    projection_version: int
    state_hash: Digest
    command_ordinal: int
    through_event_seq: int
    through_event_id: uuid.UUID | None
    simulated_seconds: int | None
    held_at: datetime
    released_at: datetime | None = None


class CheckpointHoldStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    hold: CheckpointHold
    status: Literal["DRAINING", "READY", "RELEASED"]
    pending_events: int

    @classmethod
    def read(cls, hold: CheckpointHold, pending_events: int = 0) -> CheckpointHoldStatus:
        status: Literal["DRAINING", "READY", "RELEASED"]
        if hold.released_at is not None:
            status = "RELEASED"
        else:
            status = "DRAINING" if pending_events else "READY"
        return cls(hold=hold, status=status, pending_events=pending_events)


class CheckpointHolds(Protocol):
    def active(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus | None: ...

    def begin(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus: ...

    def read(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus: ...

    def release(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus: ...


def require_checkpoint_open(cursor: PgCursor, world: uuid.UUID, branch: uuid.UUID) -> None:
    """Call under the same branch lock that serializes new action commits."""
    cursor.execute(
        "SELECT 1 FROM sim.branches WHERE (world_id,id)=(%s,%s) "
        "AND branch_kind='CANONICAL' AND status<>'ACTIVE'",
        (str(world), str(branch)),
    )
    if cursor.fetchone() is not None:
        raise BranchCheckpointHeld("canonical continuation was superseded")
    cursor.execute(
        "SELECT 1 FROM sim.campaign_checkpoint_holds WHERE (world_id,branch_id)=(%s,%s) "
        "AND released_at IS NULL",
        (str(world), str(branch)),
    )
    if cursor.fetchone() is not None:
        raise BranchCheckpointHeld("branch is paused for a checkpoint")


class PostgresCheckpointHolds:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @staticmethod
    def authorize(
        cursor: RealDictCursor, world: uuid.UUID, actor: uuid.UUID, *, private: bool = False
    ) -> None:
        required = CHECKPOINT_AUTHORITY
        if private:
            required = required | {"world.read", "entity.read.secret"}
        cursor.execute(
            "SELECT c.capability FROM sim.actor_capabilities c "
            "JOIN sim.actors a ON a.id=c.actor_id "
            "WHERE c.world_id=%s AND c.actor_id=%s AND a.is_active "
            "AND c.capability=ANY(%s::text[]) FOR SHARE OF c,a",
            (str(world), str(actor), sorted(required)),
        )
        if {row["capability"] for row in cursor} != required:
            raise PermissionError("checkpoint requires current world manager authority")

    @staticmethod
    def _require_branch(
        cursor: PgCursor, world: uuid.UUID, branch: uuid.UUID, *, lock: bool = False
    ) -> None:
        cursor.execute(
            "SELECT 1 FROM sim.branches WHERE (world_id,id)=(%s,%s) "
            "AND branch_kind='CANONICAL' AND status='ACTIVE'" + (" FOR UPDATE" if lock else ""),
            (str(world), str(branch)),
        )
        if cursor.fetchone() is None:
            raise KeyError(branch)

    @staticmethod
    def _read_hold(cursor: RealDictCursor, scope: tuple[str, str, str]) -> CheckpointHold | None:
        cursor.execute(
            "SELECT * FROM sim.campaign_checkpoint_holds "
            "WHERE (world_id,branch_id,request_id)=(%s,%s,%s)",
            scope,
        )
        row = cursor.fetchone()
        return CheckpointHold.model_validate(row) if row is not None else None

    @staticmethod
    def _status(cursor: RealDictCursor, hold: CheckpointHold) -> CheckpointHoldStatus:
        if hold.released_at is not None:
            return CheckpointHoldStatus.read(hold)
        cursor.execute(
            "SELECT count(*) AS pending FROM sim.outbox work "
            "JOIN sim.events event ON event.event_id=work.event_id "
            "WHERE (event.world_id,event.branch_id)=(%s,%s) AND event.seq_id<=%s "
            "AND work.published_at IS NULL",
            (str(hold.world_id), str(hold.branch_id), hold.through_event_seq),
        )
        row = cursor.fetchone()
        assert row is not None
        return CheckpointHoldStatus.read(hold, int(row["pending"]))

    def begin(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus:
        scope = (str(world), str(branch), str(request))
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.authorize(cursor, world, actor)
                self._require_branch(cursor, world, branch, lock=True)
                prior = self._read_hold(cursor, scope)
                if prior is not None:
                    return self._status(cursor, prior)
                try:
                    require_checkpoint_open(cursor, world, branch)
                except BranchCheckpointHeld:
                    raise CheckpointHoldConflict("another checkpoint holds this branch") from None
                cursor.execute(
                    """INSERT INTO sim.campaign_checkpoint_holds (
                      world_id, branch_id, request_id, actor_id, projection_version, state_hash,
                      command_ordinal, through_event_seq, through_event_id, simulated_seconds
                    )
                    SELECT p.world_id, p.branch_id, %s, %s, p.version, p.state_hash,
                           (SELECT count(*) FROM sim.command_log c
                             WHERE (c.world_id,c.branch_id)=(p.world_id,p.branch_id)),
                           COALESCE(last_event.seq_id,0), last_event.event_id,
                           (p.state->'tabletop.clock'->'singleton'->>'seconds')::bigint
                    FROM sim.branch_projections p
                    LEFT JOIN LATERAL (
                      SELECT e.seq_id,e.event_id FROM sim.events e
                      WHERE (e.world_id,e.branch_id)=(p.world_id,p.branch_id)
                      ORDER BY e.seq_id DESC LIMIT 1
                    ) last_event ON TRUE
                    WHERE (p.world_id,p.branch_id)=(%s,%s)
                    RETURNING *""",
                    (str(request), str(actor), *scope[:2]),
                )
                row = cursor.fetchone()
                if row is None:
                    raise ValueError("checkpoint branch projection is unavailable")
                return self._status(cursor, CheckpointHold.model_validate(row))

    def read(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus:
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.authorize(cursor, world, actor)
                self._require_branch(cursor, world, branch)
                hold = self._read_hold(cursor, (str(world), str(branch), str(request)))
                if hold is None:
                    raise KeyError(request)
                return self._status(cursor, hold)

    def active(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus | None:
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.authorize(cursor, world, actor)
                self._require_branch(cursor, world, branch)
                cursor.execute(
                    "SELECT * FROM sim.campaign_checkpoint_holds "
                    "WHERE (world_id,branch_id)=(%s,%s) AND released_at IS NULL",
                    (str(world), str(branch)),
                )
                row = cursor.fetchone()
                return self._status(cursor, CheckpointHold.model_validate(row)) if row else None

    def release(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus:
        scope = (str(world), str(branch), str(request))
        with transaction(actor_id=actor, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.authorize(cursor, world, actor)
                self._require_branch(cursor, world, branch, lock=True)
                hold = self._read_hold(cursor, scope)
                if hold is None:
                    raise KeyError(request)
                if hold.released_at is not None:
                    return CheckpointHoldStatus.read(hold)
                cursor.execute(
                    "UPDATE sim.campaign_checkpoint_holds SET released_at=clock_timestamp() "
                    "WHERE (world_id,branch_id,request_id)=(%s,%s,%s) RETURNING *",
                    scope,
                )
                released = cursor.fetchone()
                if released is None:
                    raise PermissionError("checkpoint release requires current authority")
                return CheckpointHoldStatus.read(CheckpointHold.model_validate(released))

    def lock_for_capture(
        self, cursor: RealDictCursor, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID
    ) -> CheckpointHoldStatus:
        self._require_branch(cursor, world, branch, lock=True)
        hold = self._read_hold(cursor, (str(world), str(branch), str(request)))
        if hold is None:
            raise KeyError(request)
        return self._status(cursor, hold)


class ReferenceCheckpointHolds:
    def __init__(self, simulation: SimulationApplication) -> None:
        self.simulation = simulation
        self._holds: dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID], CheckpointHold] = {}
        self._active: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}

    def held(self, world: uuid.UUID, branch: uuid.UUID) -> bool:
        return (world, branch) in self._active

    def _authorize(self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID) -> None:
        if not self.simulation.authority(world, actor).has_capabilities(CHECKPOINT_AUTHORITY):
            raise PermissionError("checkpoint requires current world manager authority")
        try:
            state = self.simulation.states.get(branch)
        except BranchIsolationError:
            raise KeyError(branch) from None
        if (state.world_id, state.kind) != (world, BranchKind.CANONICAL):
            raise KeyError(branch)

    def begin(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus:
        def freeze() -> CheckpointHoldStatus:
            self._authorize(world, branch, actor)
            key = (world, branch, request)
            if prior := self._holds.get(key):
                return CheckpointHoldStatus.read(prior)
            if self.held(world, branch):
                raise CheckpointHoldConflict("another checkpoint holds this branch")
            state = self.simulation.states.get(branch)
            history = self.simulation.command_history.get(branch, ())
            latest = next(
                (
                    (sequence, event.event_id)
                    for sequence, event in reversed(
                        tuple(enumerate(self.simulation.events.values(), start=1))
                    )
                    if (event.world_id, event.branch_id) == (world, branch)
                ),
                (0, None),
            )
            hold = CheckpointHold(
                world_id=world,
                branch_id=branch,
                request_id=request,
                actor_id=actor,
                projection_version=state.version,
                state_hash=state.state_hash,
                command_ordinal=len(history),
                through_event_seq=latest[0],
                through_event_id=latest[1],
                simulated_seconds=state.projections.get("tabletop.clock", {})
                .get("singleton", {})
                .get("seconds"),
                held_at=datetime.now(UTC),
            )
            self._holds[key] = hold
            self._active[(world, branch)] = request
            return CheckpointHoldStatus.read(hold)

        return self.simulation.read_reference(freeze)

    def read(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus:
        def check() -> CheckpointHoldStatus:
            self._authorize(world, branch, actor)
            return CheckpointHoldStatus.read(self._holds[(world, branch, request)])

        return self.simulation.read_reference(check)

    def active(
        self, world: uuid.UUID, branch: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus | None:
        def check() -> CheckpointHoldStatus | None:
            self._authorize(world, branch, actor)
            request = self._active.get((world, branch))
            if request is None:
                return None
            return CheckpointHoldStatus.read(self._holds[(world, branch, request)])

        return self.simulation.read_reference(check)

    def release(
        self, world: uuid.UUID, branch: uuid.UUID, request: uuid.UUID, actor: uuid.UUID
    ) -> CheckpointHoldStatus:
        def resume() -> CheckpointHoldStatus:
            self._authorize(world, branch, actor)
            key = (world, branch, request)
            hold = self._holds[key]
            if hold.released_at is None:
                hold = hold.model_copy(update={"released_at": datetime.now(UTC)})
                self._holds[key] = hold
                del self._active[(world, branch)]
            return CheckpointHoldStatus.read(hold)

        return self.simulation.read_reference(resume)
