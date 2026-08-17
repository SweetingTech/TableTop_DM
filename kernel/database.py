"""Small, explicit PostgreSQL boundary used by the kernel repositories.

The process never connects as the schema owner in normal operation.  Actor
identity is transaction-local so row-level security fails closed when callers
forget to supply it.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PgConnection


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required for durable storage")
    return value


@contextmanager
def transaction(
    *, actor_id: uuid.UUID | None = None, dsn: str | None = None
) -> Iterator[PgConnection]:
    connection = psycopg2.connect(dsn or database_url(), application_name="tabletop-dm-kernel")
    connection.autocommit = False
    try:
        if actor_id is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('app.actor_id', %s, true)",
                    (str(actor_id),),
                )
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def execute_one(
    statement: str,
    parameters: Sequence[Any] = (),
    *,
    actor_id: uuid.UUID | None = None,
    dsn: str | None = None,
) -> dict[str, Any] | None:
    with transaction(actor_id=actor_id, dsn=dsn) as connection:
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(statement, tuple(parameters))
            row = cursor.fetchone()
            return dict(row) if row is not None else None
