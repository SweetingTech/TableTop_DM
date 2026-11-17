"""Recoverable operational leases for canonical clock commands."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from kernel.contracts import CommandProposal
from kernel.database import transaction

if TYPE_CHECKING:
    from domains.tabletop.world_time import Clock


class ClockLeaseLost(ValueError):
    """The queue no longer authorizes this worker to commit the tick."""


class PostgresDueWork:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def claim(
        self, world_id: uuid.UUID, branch_id: uuid.UUID, clock: Clock, boundary: datetime
    ) -> uuid.UUID | None:
        token = uuid.uuid4()
        with transaction(actor_id=clock.executor_actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sim.world_due_work
                    SET lease_token=%s, lease_until=clock_timestamp() + interval '30 seconds'
                    WHERE (world_id,branch_id,run_id,executor_actor_id,epoch,step) =
                      (%s,%s,%s,%s,%s,%s)
                    AND available_at <= %s
                    AND (lease_until IS NULL OR lease_until <= clock_timestamp())
                    RETURNING lease_token
                    """,
                    (
                        str(token),
                        str(world_id),
                        str(branch_id),
                        str(clock.run_id),
                        str(clock.executor_actor_id),
                        clock.epoch,
                        clock.step,
                        boundary,
                    ),
                )
                return token if cursor.fetchone() else None

    def retry(self, proposal: CommandProposal, token: uuid.UUID) -> None:
        with transaction(actor_id=proposal.actor_id, dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE sim.world_due_work
                    SET attempts=LEAST(attempts + 1, 30),
                        available_at=GREATEST(due_at, clock_timestamp() +
                          make_interval(secs => LEAST(60, power(2, LEAST(attempts, 6)))::int)),
                        lease_token=NULL, lease_until=NULL
                    WHERE (world_id,branch_id,run_id,executor_actor_id,lease_token) =
                      (%s,%s,%s,%s,%s)
                    AND lease_until > clock_timestamp()
                    """,
                    tuple(
                        map(
                            str,
                            (
                                proposal.world_id,
                                proposal.branch_id,
                                proposal.run_id,
                                proposal.actor_id,
                                token,
                            ),
                        )
                    ),
                )


def require_tick_work(cursor: Any, proposal: CommandProposal) -> None:
    parameters = proposal.parameters
    cursor.execute(
        """
        SELECT lease_token, lease_until
        FROM sim.world_due_work
        WHERE (world_id,branch_id,run_id,executor_actor_id,epoch,step) =
          (%s,%s,%s,%s,%s,%s) AND available_at <= %s
        FOR UPDATE
        """,
        (
            str(proposal.world_id),
            str(proposal.branch_id),
            str(proposal.run_id),
            str(proposal.actor_id),
            parameters["epoch"],
            parameters["step"],
            parameters["wall_time"],
        ),
    )
    row = cursor.fetchone()
    token = parameters.get("lease_token")
    if row is None:
        raise ClockLeaseLost("clock tick has no current due work")
    cursor.execute("SELECT clock_timestamp() AS now")
    held = row["lease_until"] is not None and row["lease_until"] > cursor.fetchone()["now"]
    if token is not None and (not held or str(token) != str(row["lease_token"])):
        raise ClockLeaseLost("clock tick has no current due work lease")
    if token is None and held:
        raise ClockLeaseLost("clock tick is leased to a worker")


def replace_clock_work(cursor: Any, proposal: CommandProposal, clock: Clock | None) -> None:
    scope = (str(proposal.world_id), str(proposal.branch_id))
    if clock is None or clock.paused:
        cursor.execute("DELETE FROM sim.world_due_work WHERE (world_id,branch_id)=(%s,%s)", scope)
        return
    cursor.execute(
        """
        INSERT INTO sim.world_due_work
          (world_id,branch_id,run_id,executor_actor_id,epoch,step,due_at,available_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (world_id,branch_id) DO UPDATE SET
          run_id=EXCLUDED.run_id, executor_actor_id=EXCLUDED.executor_actor_id,
          epoch=EXCLUDED.epoch, step=EXCLUDED.step, due_at=EXCLUDED.due_at,
          available_at=EXCLUDED.available_at, lease_token=NULL, lease_until=NULL, attempts=0
        """,
        (
            *scope,
            str(clock.run_id),
            str(clock.executor_actor_id),
            clock.epoch,
            clock.step,
            clock.next_due,
            clock.next_due,
        ),
    )
