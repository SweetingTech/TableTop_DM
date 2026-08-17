#!/usr/bin/env python3
"""Strict, checksummed PostgreSQL migration runner for TableTop DM v2."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = ROOT / "infra" / "sql" / "migrations"
MIGRATION_NAME = re.compile(r"^[0-9]{3}_[a-z0-9_]+\.sql$")
LOCK_ID = 824_602_170_201


class MigrationError(RuntimeError):
    """Raised when the database and migration directory disagree."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sql: str
    checksum: str


def discover(directory: Path) -> tuple[Migration, ...]:
    if not directory.is_dir():
        raise MigrationError(f"migration directory does not exist: {directory}")
    migrations: list[Migration] = []
    for path in sorted(directory.iterdir()):
        if path.is_dir() or path.name.startswith("."):
            continue
        if path.suffix != ".sql" or not MIGRATION_NAME.fullmatch(path.name):
            raise MigrationError(f"invalid migration filename: {path.name}")
        body = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=path.name,
                path=path,
                sql=body,
                checksum=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            )
        )
    if not migrations:
        raise MigrationError(f"migration directory has no SQL migrations: {directory}")
    versions = [migration.version[:3] for migration in migrations]
    expected = [f"{number:03d}" for number in range(1, len(migrations) + 1)]
    if versions != expected:
        raise MigrationError(
            f"migration versions must be contiguous from 001: found {versions}, expected {expected}"
        )
    return tuple(migrations)


def connect_with_retry(dsn: str, wait_seconds: float):
    deadline = time.monotonic() + max(0, wait_seconds)
    while True:
        try:
            return psycopg2.connect(dsn, connect_timeout=5)
        except psycopg2.Error as exc:
            if time.monotonic() >= deadline:
                raise MigrationError(f"database is unavailable: {exc}") from exc
            time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))


def bootstrap_migration_table(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS infra_meta")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS infra_meta.schema_migrations (
              version text PRIMARY KEY,
              checksum text NOT NULL
                CONSTRAINT ck_infra_schema_migrations_checksum
                CHECK (checksum ~ '^[0-9a-f]{64}$'),
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    connection.commit()


def applied_migrations(connection) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT version, checksum FROM infra_meta.schema_migrations ORDER BY version"
        )
        return dict(cursor.fetchall())


def verify_state(
    migrations: tuple[Migration, ...], applied: dict[str, str], *, require_current: bool
) -> tuple[Migration, ...]:
    on_disk = {migration.version: migration for migration in migrations}
    removed = sorted(set(applied) - set(on_disk))
    if removed:
        raise MigrationError("database contains migrations absent from disk: " + ", ".join(removed))
    for version, checksum in applied.items():
        expected = on_disk[version].checksum
        if checksum != expected:
            raise MigrationError(
                f"checksum drift for {version}: database={checksum}, disk={expected}"
            )
    pending = tuple(migration for migration in migrations if migration.version not in applied)
    if require_current and pending:
        raise MigrationError(
            "database has unapplied migrations: "
            + ", ".join(migration.version for migration in pending)
        )
    return pending


def apply_pending(connection, pending: tuple[Migration, ...]) -> None:
    for migration in pending:
        try:
            with connection.cursor() as cursor:
                cursor.execute(migration.sql)
                cursor.execute(
                    """
                    INSERT INTO infra_meta.schema_migrations(version, checksum)
                    VALUES (%s, %s)
                    """,
                    (migration.version, migration.checksum),
                )
            connection.commit()
            print(f"applied {migration.version}")
        except Exception:
            connection.rollback()
            raise


def ensure_runtime_login(connection, username: str, password: str) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", username):
        raise MigrationError("APP_DATABASE_USER must be a safe PostgreSQL identifier")
    if not password:
        raise MigrationError("APP_DATABASE_PASSWORD must not be empty")
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
        exists = cursor.fetchone() is not None
        identifier = sql.Identifier(username)
        statement = (
            "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOBYPASSRLS NOREPLICATION INHERIT PASSWORD %s"
            if exists
            else "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOBYPASSRLS NOREPLICATION INHERIT PASSWORD %s"
        )
        cursor.execute(sql.SQL(statement).format(identifier), (password,))
        cursor.execute(sql.SQL("GRANT tabletop_app TO {}").format(identifier))
        cursor.execute(
            """
            SELECT parent.rolname
            FROM pg_auth_members membership
            JOIN pg_roles member ON member.oid = membership.member
            JOIN pg_roles parent ON parent.oid = membership.roleid
            WHERE member.rolname = %s AND parent.rolname <> 'tabletop_app'
            ORDER BY parent.rolname
            """,
            (username,),
        )
        unexpected_memberships = [row[0] for row in cursor.fetchall()]
        if unexpected_memberships:
            raise MigrationError(
                f"runtime role {username} has unexpected memberships: "
                + ", ".join(unexpected_memberships)
            )
    connection.commit()


def migrate(
    dsn: str,
    directory: Path,
    *,
    check_only: bool = False,
    wait_seconds: float = 0,
    runtime_user: str | None = None,
    runtime_password: str | None = None,
) -> int:
    migrations = discover(directory)
    connection = connect_with_retry(dsn, wait_seconds)
    try:
        bootstrap_migration_table(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        applied = applied_migrations(connection)
        pending = verify_state(migrations, applied, require_current=check_only)
        if not check_only:
            apply_pending(connection, pending)
            if runtime_user is not None:
                ensure_runtime_login(connection, runtime_user, runtime_password or "")
            verify_state(migrations, applied_migrations(connection), require_current=True)
        noun = "migration" if len(migrations) == 1 else "migrations"
        print(f"migration state current ({len(migrations)} {noun})")
        return len(pending)
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
            connection.commit()
        finally:
            connection.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail unless schema is current")
    parser.add_argument("--wait", type=float, default=0, metavar="SECONDS")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_ADMIN_URL") or os.environ.get("DATABASE_URL"),
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=Path(os.environ.get("TTDM_MIGRATIONS_DIR", DEFAULT_MIGRATIONS_DIR)),
    )
    parser.add_argument(
        "--skip-runtime-role",
        action="store_true",
        help="do not create/update the least-privilege runtime login",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        print("DATABASE_ADMIN_URL or DATABASE_URL is required", file=sys.stderr)
        return 2
    try:
        migrate(
            args.database_url,
            args.migrations_dir.resolve(),
            check_only=args.check,
            wait_seconds=args.wait,
            runtime_user=(
                None
                if args.check or args.skip_runtime_role
                else os.environ.get("APP_DATABASE_USER", "tabletop_runtime")
            ),
            runtime_password=os.environ.get("APP_DATABASE_PASSWORD", ""),
        )
    except (MigrationError, psycopg2.Error) as exc:
        print(f"migration error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
