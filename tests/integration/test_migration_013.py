from __future__ import annotations

import shutil
import uuid
from contextlib import closing
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import migrate

pytestmark = pytest.mark.integration


def test_roster_revocation_clean_upgrade_rollback_and_repeat(integration_stack, tmp_path):
    name = "ttdm_roster_upgrade_" + uuid.uuid4().hex
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    url = make_dsn(integration_stack.admin_url, dbname=name)
    migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
    prior = tmp_path / "prior"
    prior.mkdir()
    for path in sorted(migrations.glob("*.sql"))[:12]:
        shutil.copy2(path, prior / path.name)
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        assert migrate(url, prior) == 12
        with closing(psycopg2.connect(url)) as connection, connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_get_functiondef("
                    "'sim.runtime_controls_entity(uuid,uuid,uuid)'::regprocedure)"
                )
                original = cursor.fetchone()[0]
                cursor.execute((migrations / "013_roster_controller_revocation.sql").read_text())
                connection.rollback()
                cursor.execute(
                    "SELECT pg_get_functiondef("
                    "'sim.runtime_controls_entity(uuid,uuid,uuid)'::regprocedure)"
                )
                assert cursor.fetchone()[0] == original
        shutil.copy2(migrations / "013_roster_controller_revocation.sql", prior)
        assert migrate(url, prior) == 1
        assert migrate(url, prior) == 0
        with (
            closing(psycopg2.connect(url)) as connection,
            connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "SELECT prosecdef, proacl::text, pg_get_functiondef(oid) FROM pg_proc "
                "WHERE oid='sim.runtime_controls_entity(uuid,uuid,uuid)'::regprocedure"
            )
            definer, acl, definition = cursor.fetchone()
            assert definer is False
            assert "tabletop_app=X" in acl
            assert "seat_removed" in definition
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_proc p, aclexplode(p.proacl) a "
                "WHERE p.oid='sim.runtime_controls_entity(uuid,uuid,uuid)'::regprocedure "
                "AND a.grantee=0)"
            )
            assert cursor.fetchone()[0] is False
    finally:
        # Only this test's literal, freshly created database is dropped.
        assert name.startswith("ttdm_roster_upgrade_") and len(name) == 52
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        maintenance.close()
