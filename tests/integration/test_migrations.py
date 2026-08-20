from __future__ import annotations

import shutil
from pathlib import Path

import psycopg2
import pytest

from infra.migrate import MigrationError, migrate

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_fresh_baseline_and_idempotent_rerun(integration_stack) -> None:
    assert (
        migrate(
            integration_stack.admin_url,
            ROOT / "infra" / "sql" / "migrations",
            check_only=True,
        )
        == 0
    )
    assert (
        migrate(
            integration_stack.admin_url,
            ROOT / "infra" / "sql" / "migrations",
            runtime_user=integration_stack.runtime_user,
            runtime_password=integration_stack.runtime_password,
        )
        == 0
    )
    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT version FROM infra_meta.schema_migrations")
        assert cursor.fetchall() == [
            ("001_simulation_kernel.sql",),
            ("002_identity_and_tabletop_workspaces.sql",),
        ]
        cursor.execute(
            """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name = ANY(%s)
            ORDER BY schema_name
            """,
            (
                [
                    "artifacts",
                    "cognition",
                    "experiments",
                    "persona",
                    "population",
                    "sim",
                ],
            ),
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "artifacts",
            "cognition",
            "experiments",
            "persona",
            "population",
            "sim",
        ]


def test_checksum_drift_fails_closed(integration_stack, tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    shutil.copytree(ROOT / "infra" / "sql" / "migrations", migration_dir)
    baseline = migration_dir / "001_simulation_kernel.sql"
    baseline.write_text(baseline.read_text(encoding="utf-8") + "\n-- drift\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="checksum drift"):
        migrate(integration_stack.admin_url, migration_dir, check_only=True)


def test_runtime_role_is_least_privilege(integration_stack) -> None:
    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication,
                   rolbypassrls, rolinherit
            FROM pg_roles WHERE rolname = %s
            """,
            (integration_stack.runtime_user,),
        )
        assert cursor.fetchone() == (False, False, False, False, False, True)

    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
        pytest.raises(psycopg2.errors.InsufficientPrivilege),
    ):
        cursor.execute("CREATE SCHEMA forbidden")


def test_migration_history_is_constrained_and_append_only(integration_stack) -> None:
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with (
            connection.cursor() as cursor,
            pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState, match="append-only"),
        ):
            cursor.execute(
                "UPDATE infra_meta.schema_migrations SET checksum = %s",
                ("0" * 64,),
            )
        connection.rollback()

        with (
            connection.cursor() as cursor,
            pytest.raises(psycopg2.errors.CheckViolation),
        ):
            cursor.execute(
                """
                INSERT INTO infra_meta.schema_migrations(version, checksum)
                VALUES ('999_invalid.sql', 'invalid')
                """
            )
        connection.rollback()
