from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg2
import pytest
from psycopg2 import sql

from infra.migrate import migrate


@dataclass(frozen=True)
class IntegrationStack:
    admin_url: str
    database_url: str
    redis_url: str
    database_name: str
    runtime_user: str
    runtime_password: str


def _with_database(
    url: str, database: str, *, username: str | None = None, password: str | None = None
) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme.startswith("postgres"):
        raise RuntimeError("integration database URL must be a PostgreSQL URL")
    host = parsed.hostname or "127.0.0.1"
    netloc = ""
    selected_user = username if username is not None else parsed.username
    selected_password = password if password is not None else parsed.password
    if selected_user:
        netloc = quote(selected_user, safe="")
        if selected_password is not None:
            netloc += ":" + quote(selected_password, safe="")
        netloc += "@"
    netloc += host
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, f"/{database}", "", ""))


@pytest.fixture(scope="session")
def integration_stack() -> IntegrationStack:
    if os.environ.get("TTDM_INTEGRATION") != "1":
        pytest.skip("set TTDM_INTEGRATION=1 and start PostgreSQL/Redis to run integration tests")

    maintenance_url = os.environ.get(
        "TTDM_TEST_DATABASE_ADMIN_URL",
        "postgresql://postgres:postgres_dev_only@127.0.0.1:5432/postgres",
    )
    suffix = f"{os.getpid()}_{secrets.token_hex(3)}"
    database_name = f"tabletop_dm_test_{suffix}"
    runtime_user = f"ttdm_test_{suffix}"
    runtime_password = secrets.token_urlsafe(24)

    maintenance = psycopg2.connect(maintenance_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    finally:
        maintenance.close()

    admin_url = _with_database(maintenance_url, database_name)
    runtime_url = _with_database(
        maintenance_url,
        database_name,
        username=runtime_user,
        password=runtime_password,
    )
    migrate(
        admin_url,
        directory=Path(__file__).resolve().parents[2] / "infra" / "sql" / "migrations",
        runtime_user=runtime_user,
        runtime_password=runtime_password,
    )
    stack = IntegrationStack(
        admin_url=admin_url,
        database_url=runtime_url,
        redis_url=os.environ.get(
            "TTDM_TEST_REDIS_URL", "redis://:redis_dev_only@127.0.0.1:6379/15"
        ),
        database_name=database_name,
        runtime_user=runtime_user,
        runtime_password=runtime_password,
    )
    yield stack

    maintenance = psycopg2.connect(maintenance_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(runtime_user)))
    finally:
        maintenance.close()
