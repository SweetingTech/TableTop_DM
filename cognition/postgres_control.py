# ruff: noqa: E501 -- keep SQL contracts readable beside their values.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg2.extras

from cognition.control import (
    EXECUTOR_CAPABILITIES,
    ControlConflict,
    HandoffReceipt,
    HandoffRequest,
    RecapWindow,
    deferred_controller,
    disconnect_due,
    disconnect_handoff,
    next_controller,
    recap_bounds,
    renew_presence,
)
from kernel.control import ControllerState, ControlScope, persist_controller
from kernel.database import transaction

PRESENCE_BATCH_LIMIT = 32


class PostgresControllers:
    def __init__(self, dsn: str, machine_actor_id: uuid.UUID) -> None:
        self.dsn, self.machine_actor_id = dsn, machine_actor_id
        self._last_presence_scan: tuple[datetime, str, str, str, str] | None = None

    @staticmethod
    def _owner(cursor, scope: ControlScope, actor_id: uuid.UUID) -> uuid.UUID:
        cursor.execute(
            """
            SELECT e.controller_actor_id FROM sim.entities e JOIN sim.runs r
              ON (r.world_id,r.branch_id,r.id)=(e.world_id,e.branch_id,%s)
            JOIN sim.branches b ON (b.world_id,b.id)=(e.world_id,e.branch_id)
            WHERE (e.world_id,e.branch_id,e.id)=(%s,%s,%s)
              AND (e.controller_actor_id=sim.current_actor_id()
                   OR sim.has_world_capability(e.world_id,'mind.write.all'))
            """,
            (str(scope.run_id), str(scope.world_id), str(scope.branch_id), str(scope.entity_id)),
        )
        row = cursor.fetchone()
        if row is None:
            raise PermissionError("actor cannot manage this controller")
        return (
            uuid.UUID(str(row["controller_actor_id"])) if row["controller_actor_id"] else actor_id
        )

    @staticmethod
    def _read(cursor, scope: ControlScope) -> ControllerState | None:
        cursor.execute(
            "SELECT payload FROM cognition.controller_assignments WHERE "
            "(world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s)",
            tuple(map(str, scope.key)),
        )
        row = cursor.fetchone()
        return ControllerState.model_validate(row["payload"]) if row else None

    @staticmethod
    def _database_clock(cursor) -> datetime:
        cursor.execute("SELECT clock_timestamp() AS current_time_utc")
        current: datetime = cursor.fetchone()["current_time_utc"]
        return current.astimezone(UTC)

    @staticmethod
    def _check_player(cursor, scope: ControlScope, actor_id: uuid.UUID) -> None:
        cursor.execute(
            """
            SELECT 1 FROM sim.entities e JOIN sim.actors a ON a.id=e.controller_actor_id
            WHERE (e.world_id,e.branch_id,e.id)=(%s,%s,%s) AND a.id=%s
              AND e.entity_type='PLAYER_CHARACTER' AND a.actor_kind='HUMAN' AND a.is_active
              AND (SELECT count(DISTINCT ac.capability) FROM sim.actor_capabilities ac
                   WHERE ac.world_id=e.world_id AND ac.actor_id=a.id
                   AND ac.capability=ANY(%s::text[]))=%s
            """,
            (
                str(scope.world_id),
                str(scope.branch_id),
                str(scope.entity_id),
                str(actor_id),
                sorted(EXECUTOR_CAPABILITIES),
                len(EXECUTOR_CAPABILITIES),
            ),
        )
        if cursor.fetchone() is None:
            raise PermissionError("controller presence requires the current human player")

    @staticmethod
    def _lock_branch(cursor, scope: ControlScope) -> None:
        cursor.execute(
            "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE",
            tuple(map(str, scope.key[:2])),
        )

    @staticmethod
    def _branch_revision(cursor, scope: ControlScope) -> int:
        cursor.execute(
            "SELECT version FROM sim.branch_projections WHERE (world_id,branch_id)=(%s,%s)",
            tuple(map(str, scope.key[:2])),
        )
        row = cursor.fetchone()
        if row is None:
            raise ControlConflict("controller branch is unavailable")
        return int(row["version"])

    def get(self, scope: ControlScope, actor_id: uuid.UUID) -> ControllerState | None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._owner(cursor, scope, actor_id)
                return self._read(cursor, scope)

    def handoff(
        self, scope: ControlScope, actor_id: uuid.UUID, request: HandoffRequest
    ) -> HandoffReceipt:
        try:
            return self._handoff(scope, actor_id, request)
        except psycopg2.Error:
            raise ValueError("controller handoff could not be stored; reload and retry") from None

    def _handoff(
        self,
        scope: ControlScope,
        actor_id: uuid.UUID,
        request: HandoffRequest,
        *,
        timeout_at: datetime | None = None,
    ) -> HandoffReceipt:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._owner(cursor, scope, actor_id)
                cursor.execute(
                    "SELECT id FROM sim.runs WHERE (world_id,branch_id,id)=(%s,%s,%s) "
                    "FOR NO KEY UPDATE",
                    tuple(map(str, scope.key[:3])),
                )
                self._lock_branch(cursor, scope)
                owner = self._owner(cursor, scope, actor_id)
                cursor.execute(
                    "SELECT sim.has_world_capability(%s,'action.propose') AND "
                    "sim.has_world_capability(%s,'action.commit') AND "
                    "(%s<>'AUTONOMOUS' OR sim.has_world_capability(%s,'entity.act')) AS allowed",
                    (str(scope.world_id), str(scope.world_id), request.mode, str(scope.world_id)),
                )
                permission = cursor.fetchone()
                if permission is None or not permission["allowed"]:
                    raise PermissionError("actor lacks controller execution capabilities")
                cursor.execute(
                    "SELECT r.run_kind,r.status,b.branch_kind FROM sim.runs r "
                    "JOIN sim.branches b ON (b.world_id,b.id)=(r.world_id,r.branch_id) "
                    "WHERE (r.world_id,r.branch_id,r.id)=(%s,%s,%s)",
                    tuple(map(str, scope.key[:3])),
                )
                lineage = cursor.fetchone()
                if lineage is None or (lineage["run_kind"], lineage["branch_kind"]) != (
                    "LIVE",
                    "CANONICAL",
                ):
                    raise ValueError("controllers require a canonical live run")
                cursor.execute(
                    "SELECT payload FROM cognition.controller_handoffs WHERE "
                    "(world_id,branch_id,run_id,entity_id,actor_id,idempotency_key)=(%s,%s,%s,%s,%s,%s)",
                    (*map(str, scope.key), str(actor_id), request.idempotency_key),
                )
                prior = cursor.fetchone()
                if prior:
                    return HandoffReceipt.model_validate(prior["payload"])
                previous = self._read(cursor, scope)
                if "disconnect_after_seconds" in request.model_fields_set:
                    self._check_player(cursor, scope, actor_id)
                if timeout_at is not None:
                    self._check_player(cursor, scope, owner)
                    if (
                        previous is None
                        or previous.owner_actor_id != owner
                        or not disconnect_due(previous, timeout_at)
                        or lineage["status"] not in {"ACTIVE", "RUNNING"}
                    ):
                        raise ControlConflict("controller presence changed")
                if request.mode == "AUTONOMOUS" or request.disconnect_after_seconds is not None:
                    cursor.execute(
                        "SELECT 1 FROM tabletop.character_bindings WHERE "
                        "(world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) LIMIT 1",
                        tuple(map(str, scope.key)),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError(
                            "a pinned CHARACTER binding is required before autonomous play"
                        )
                state = next_controller(
                    scope,
                    actor_id,
                    owner,
                    request,
                    previous,
                    disconnected=timeout_at is not None,
                    presence_now=self._database_clock(cursor) if request.mode == "HUMAN" else None,
                )
                cursor.execute(
                    "INSERT INTO sim.actors(id,actor_kind,display_name) "
                    "VALUES (%s,'AGENT','Character policy executor') ON CONFLICT (id) DO NOTHING",
                    (str(state.executor_actor_id),),
                )
                cursor.execute(
                    "SELECT actor_kind FROM sim.actors WHERE id=%s", (str(state.executor_actor_id),)
                )
                executor = cursor.fetchone()
                if executor is None or executor["actor_kind"] != "AGENT":
                    raise ValueError("execution principal is unavailable")
                for capability in sorted(EXECUTOR_CAPABILITIES):
                    cursor.execute(
                        "INSERT INTO sim.actor_capabilities(world_id,actor_id,capability) "
                        "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (str(scope.world_id), str(state.executor_actor_id), capability),
                    )
                cursor.execute(
                    """INSERT INTO cognition.runtime_assignments
                    (world_id,branch_id,run_id,entity_id,runtime_kind,runtime_config,assigned_at)
                    VALUES (%s,%s,%s,%s,%s,'{}'::jsonb,now())
                    ON CONFLICT (world_id,branch_id,run_id,entity_id) DO UPDATE
                    SET runtime_kind=EXCLUDED.runtime_kind,assigned_at=EXCLUDED.assigned_at""",
                    (*map(str, scope.key), "HUMAN" if state.mode == "HUMAN" else "UTILITY"),
                )
                cursor.execute(
                    """INSERT INTO cognition.controller_assignments
                    (world_id,branch_id,run_id,entity_id,owner_actor_id,executor_actor_id,payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT (world_id,branch_id,run_id,entity_id) DO UPDATE SET payload=EXCLUDED.payload""",
                    (
                        *map(str, scope.key),
                        str(owner),
                        str(state.executor_actor_id),
                        state.model_dump_json(),
                    ),
                )
                receipt = HandoffReceipt(
                    actor_id=actor_id,
                    idempotency_key=request.idempotency_key,
                    state=state,
                    recap_revision=self._branch_revision(cursor, scope),
                )
                cursor.execute(
                    """INSERT INTO cognition.controller_handoffs
                    (receipt_id,world_id,branch_id,run_id,entity_id,actor_id,idempotency_key,payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (
                        str(uuid.uuid4()),
                        *map(str, scope.key),
                        str(actor_id),
                        request.idempotency_key,
                        receipt.model_dump_json(),
                    ),
                )
                return receipt

    def recap_window(self, scope: ControlScope, actor_id: uuid.UUID) -> RecapWindow | None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._owner(cursor, scope, actor_id)
                self._lock_branch(cursor, scope)
                self._owner(cursor, scope, actor_id)
                current = self._read(cursor, scope)
                if current is None:
                    return None
                cursor.execute(
                    "SELECT payload FROM cognition.controller_handoffs "
                    "WHERE (world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) "
                    "AND payload->'state'->>'mode'='AUTONOMOUS' "
                    "ORDER BY (payload->'state'->>'epoch')::bigint DESC LIMIT 1",
                    tuple(map(str, scope.key)),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                start = HandoffReceipt.model_validate(row["payload"])
                cursor.execute(
                    "SELECT payload FROM cognition.controller_handoffs "
                    "WHERE (world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) "
                    "AND (payload->'state'->>'epoch')::bigint>%s "
                    "ORDER BY (payload->'state'->>'epoch')::bigint LIMIT 1",
                    (*map(str, scope.key), start.state.epoch),
                )
                row = cursor.fetchone()
                end = HandoffReceipt.model_validate(row["payload"]) if row else None
                return recap_bounds(start, end, current, self._branch_revision(cursor, scope))

    def presence(
        self, scope: ControlScope, actor_id: uuid.UUID, expected_epoch: int
    ) -> ControllerState:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._owner(cursor, scope, actor_id)
                self._lock_branch(cursor, scope)
                self._check_player(cursor, scope, actor_id)
                previous = self._read(cursor, scope)
                state = renew_presence(previous, expected_epoch, now=self._database_clock(cursor))
                if state != previous:
                    persist_controller(cursor, state)
                return state

    def expire_disconnected(self, now: datetime | None = None) -> None:
        # Start after the last scanned row and wrap, even when a handoff is rejected.
        after = self._last_presence_scan or (None, None, None, None, None)
        with transaction(actor_id=self.machine_actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                if now is None:
                    now = self._database_clock(cursor)
                cursor.execute(
                    """SELECT c.payload FROM cognition.controller_assignments c
                    JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(c.world_id,c.branch_id,c.run_id)
                    WHERE c.payload->>'mode'='HUMAN'
                      AND (c.payload->>'presence_deadline_at')::timestamptz<=%s
                      AND r.status IN ('ACTIVE','RUNNING')
                    ORDER BY (
                      ((c.payload->>'presence_deadline_at')::timestamptz,
                       c.world_id,c.branch_id,c.run_id,c.entity_id)
                      <= (%s::timestamptz,%s::uuid,%s::uuid,%s::uuid,%s::uuid)
                    ), (c.payload->>'presence_deadline_at')::timestamptz,
                             c.world_id,c.branch_id,c.run_id,c.entity_id LIMIT %s""",
                    (now, *after, PRESENCE_BATCH_LIMIT),
                )
                expired = tuple(ControllerState.model_validate(row["payload"]) for row in cursor)
        if expired and (deadline := expired[-1].presence_deadline_at) is not None:
            last = expired[-1]
            self._last_presence_scan = (
                deadline,
                str(last.world_id),
                str(last.branch_id),
                str(last.run_id),
                str(last.entity_id),
            )
        else:
            self._last_presence_scan = None
        for state in expired:
            try:
                self._handoff(
                    state.scope, self.machine_actor_id, disconnect_handoff(state), timeout_at=now
                )
            except (ControlConflict, PermissionError, ValueError, psycopg2.Error):
                continue

    def due(self) -> tuple[ControllerState, ...]:
        self.expire_disconnected()
        with transaction(actor_id=self.machine_actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute("""SELECT c.payload FROM cognition.controller_assignments c
                    JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(c.world_id,c.branch_id,c.run_id)
                    WHERE c.payload->>'mode'='AUTONOMOUS'
                      AND (c.payload->>'next_due')::timestamptz<=now()
                      AND r.status IN ('RUNNING','ACTIVE')
                    ORDER BY (c.payload->>'next_due')::timestamptz,
                             c.world_id,c.branch_id,c.run_id,c.entity_id LIMIT 32""")
                return tuple(
                    ControllerState.model_validate(row["payload"]) for row in cursor.fetchall()
                )

    def defer(self, state: ControllerState, code: str | None, *, retry_limit: int = 0) -> None:
        with transaction(actor_id=state.executor_actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._lock_branch(cursor, state.scope)
                current = self._read(cursor, state.scope)
                if current != state or state.mode != "AUTONOMOUS":
                    return
                persist_controller(
                    cursor, deferred_controller(state, code, retry_limit=retry_limit)
                )
