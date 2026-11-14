# ruff: noqa: E501 -- keep SQL contracts readable beside their values.
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg2.extras

from cognition.control import EXECUTOR_CAPABILITIES, HandoffReceipt, HandoffRequest, next_controller
from kernel.control import ControllerState, ControlScope, persist_controller
from kernel.database import transaction


class PostgresControllers:
    def __init__(self, dsn: str, machine_actor_id: uuid.UUID) -> None:
        self.dsn, self.machine_actor_id = dsn, machine_actor_id

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
        self, scope: ControlScope, actor_id: uuid.UUID, request: HandoffRequest
    ) -> HandoffReceipt:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._owner(cursor, scope, actor_id)
                cursor.execute(
                    "SELECT id FROM sim.runs WHERE (world_id,branch_id,id)=(%s,%s,%s) FOR UPDATE",
                    tuple(map(str, scope.key[:3])),
                )
                cursor.execute(
                    "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE",
                    tuple(map(str, scope.key[:2])),
                )
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
                    "SELECT r.run_kind,b.branch_kind FROM sim.runs r "
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
                if request.mode == "AUTONOMOUS":
                    cursor.execute(
                        "SELECT 1 FROM tabletop.character_bindings WHERE "
                        "(world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) LIMIT 1",
                        tuple(map(str, scope.key)),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError(
                            "a pinned CHARACTER binding is required before autonomous play"
                        )
                state = next_controller(scope, actor_id, owner, request, self._read(cursor, scope))
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
                    actor_id=actor_id, idempotency_key=request.idempotency_key, state=state
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

    def due(self) -> tuple[ControllerState, ...]:
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

    def defer(self, state: ControllerState, code: str, *, pending: bool = False) -> None:
        with transaction(actor_id=state.executor_actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE",
                    tuple(map(str, state.key[:2])),
                )
                current = self._read(cursor, state.scope)
                if current is None or (current.epoch, current.step, current.mode) != (
                    state.epoch,
                    state.step,
                    "AUTONOMOUS",
                ):
                    return
                failures = current.failures + 1
                persist_controller(
                    cursor,
                    current.model_copy(
                        update={
                            "mode": "AUTONOMOUS" if pending and failures < 40 else "PAUSED",
                            "last_error": code,
                            "failures": failures,
                            "next_due": datetime.now(UTC) + timedelta(milliseconds=250),
                        }
                    ),
                )
