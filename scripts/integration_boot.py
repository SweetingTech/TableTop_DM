"""Cross-platform integration boot/reset/migrate/seed harness."""

from __future__ import annotations

import hashlib
import re
import sys

from integration_common import ROOT, ensure_env_file, psql, wait_for_postgres
import db_reset


MIGRATION_RE = re.compile(r"^[0-9]{3}_[a-z_]+\.sql$")


def _apply_migrations() -> None:
    bootstrap = """
CREATE SCHEMA IF NOT EXISTS infra_meta;
CREATE TABLE IF NOT EXISTS infra_meta.schema_migrations (
  version text PRIMARY KEY,
  checksum text NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now()
);
"""
    psql("-c", bootstrap)

    for migration in sorted((ROOT / "infra" / "sql" / "migrations").glob("*.sql")):
        version = migration.name
        if not MIGRATION_RE.match(version):
            print(
                f"Skipping migration with unsafe filename: {version}", file=sys.stderr
            )
            continue

        sql = migration.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        result = psql(
            "-At",
            "-c",
            f"SELECT checksum FROM infra_meta.schema_migrations WHERE version = '{version}';",
            capture=True,
        )
        applied_checksum = (result.stdout or "").strip()
        if applied_checksum:
            if applied_checksum != checksum:
                raise RuntimeError(
                    "checksum mismatch for already-applied migration "
                    f"{version}. Rebuild a disposable Docker dev database with "
                    "`./scripts/start.sh --mode docker --reset-db` or "
                    "`.\\scripts\\start.ps1 -Mode docker -ResetDb`."
                )
            print(f"Skipping {version} (already applied)")
            continue

        print(f"Applying {version}")
        psql(sql=sql)
        psql(
            "-c",
            "INSERT INTO infra_meta.schema_migrations(version, checksum) "
            f"VALUES ('{version}', '{checksum}');",
        )


def _seed_demo() -> None:
    seed = ROOT / "infra" / "sql" / "seed" / "001_demo_campaign.sql"
    psql(sql=seed.read_text(encoding="utf-8"))

    run_dir = ROOT / ".run"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "smoke_join_tokens.txt").write_text(
        "\n".join(
            [
                "DM=dm-smoke-join-22222222-2222-2222-2222-222222222221",
                "PLAYER=player-smoke-join-22222222-2222-2222-2222-222222222222",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _ensure_test_role() -> None:
    sql = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tabletop') THEN
    CREATE ROLE tabletop LOGIN PASSWORD 'tabletop_dev_password';
  ELSE
    ALTER ROLE tabletop WITH LOGIN PASSWORD 'tabletop_dev_password';
  END IF;
END $$;

GRANT CONNECT ON DATABASE tabletop_dm TO tabletop;
GRANT USAGE ON SCHEMA state, ledger, infra_meta TO tabletop;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA state TO tabletop;
GRANT SELECT ON ALL TABLES IN SCHEMA infra_meta TO tabletop;
GRANT SELECT, INSERT ON ledger.session_ledger TO tabletop;
GRANT SELECT, INSERT ON ledger.session_summaries TO tabletop;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA state, ledger TO tabletop;
"""
    psql(sql=sql)


def main() -> None:
    ensure_env_file()
    db_reset.main()
    wait_for_postgres()
    _apply_migrations()
    _seed_demo()
    _ensure_test_role()


if __name__ == "__main__":
    main()
