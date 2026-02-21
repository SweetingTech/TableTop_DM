#!/usr/bin/env python3
import os
import sys
import hashlib
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get("DATABASE_URL", "")
MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "sql", "migrations"
)


def run_migrations():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("""
        CREATE SCHEMA IF NOT EXISTS infra_meta;
        CREATE TABLE IF NOT EXISTS infra_meta.schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ DEFAULT now()
        );
    """)
    conn.commit()

    cur.execute(
        "SELECT version, checksum FROM infra_meta.schema_migrations ORDER BY applied_at"
    )
    applied = {row[0]: row[1] for row in cur.fetchall()}

    migration_files = sorted(
        f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")
    )
    applied_count = 0

    for filename in migration_files:
        filepath = os.path.join(MIGRATIONS_DIR, filename)
        with open(filepath, "r") as f:
            sql = f.read()

        checksum = hashlib.sha256(sql.encode()).hexdigest()

        if filename in applied:
            if applied[filename] != checksum:
                print(
                    f"  WARNING: Checksum mismatch for {filename} (applied: {applied[filename][:12]}, current: {checksum[:12]})"
                )
            continue

        print(f"  Applying migration: {filename}")
        try:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO infra_meta.schema_migrations (version, checksum) VALUES (%s, %s)",
                (filename, checksum),
            )
            conn.commit()
            applied_count += 1
        except Exception as e:
            conn.rollback()
            print(f"  ERROR applying {filename}: {e}")
            raise

    cur.close()
    conn.close()

    if applied_count > 0:
        print(f"  Applied {applied_count} new migration(s).")
    else:
        print("  All migrations already applied.")


if __name__ == "__main__":
    run_migrations()
