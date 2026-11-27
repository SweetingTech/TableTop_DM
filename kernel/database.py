"""Small, explicit PostgreSQL boundary used by the kernel repositories.

The process never connects as the schema owner in normal operation.  Actor
identity is transaction-local so row-level security fails closed when callers
forget to supply it.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PgConnection


@dataclass
class _UnitOfWork:
    connection: PgConnection
    dsn: str
    actor_id: uuid.UUID
    failed: bool = False
    after_commit: list[Callable[[], object]] = field(default_factory=list)


_unit: ContextVar[_UnitOfWork | None] = ContextVar("tabletop_database_unit", default=None)


@contextmanager
def unit_of_work(*, actor_id: uuid.UUID, dsn: str) -> Iterator[PgConnection]:
    """Explicitly compose same-actor repository writes into one outer commit.

    Ordinary transactions remain independent. A nested failure makes this entire unit
    rollback-only, even if a repository catches the exception. Actor/DSN switching is
    forbidden while sharing a connection; no RLS identity can bleed across callers.
    """
    if _unit.get() is not None:
        raise RuntimeError("nested database units are not supported")
    with transaction(actor_id=actor_id, dsn=dsn) as connection:
        active = _UnitOfWork(connection, dsn, actor_id)
        token = _unit.set(active)
        try:
            yield connection
            if active.failed:
                raise RuntimeError("database unit was rolled back after a nested failure")
        finally:
            _unit.reset(token)
    for callback in active.after_commit:
        callback()


def after_commit(callback: Callable[[], object]) -> bool:
    """Defer in-process publication until the explicitly composed DB unit commits."""
    active = _unit.get()
    if active is None:
        return False
    active.after_commit.append(callback)
    return True


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required for durable storage")
    return value


@contextmanager
def transaction(
    *,
    actor_id: uuid.UUID | None = None,
    dsn: str | None = None,
    isolation: Literal["REPEATABLE READ"] | None = None,
) -> Iterator[PgConnection]:
    active = _unit.get()
    if active is not None:
        try:
            if (dsn or database_url()) != active.dsn or actor_id not in {None, active.actor_id}:
                raise RuntimeError("database unit cannot switch actor or database")
            if isolation is not None:
                raise RuntimeError("database unit isolation must be selected before opening it")
            yield active.connection
        except BaseException:
            active.failed = True
            raise
        return
    connection = psycopg2.connect(dsn or database_url(), application_name="tabletop-dm-kernel")
    connection.autocommit = False
    try:
        if isolation is not None:
            connection.set_session(isolation_level=isolation)
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
