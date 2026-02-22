from pathlib import Path

import pytest

pytestmark = pytest.mark.contracts


def _read_state_migrations() -> str:
    migration_dir = Path("infra/sql/migrations")
    state_migrations = [
        migration_dir / "001_state_schema.sql",
        migration_dir / "004_sessions_schema_upgrade.sql",
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in state_migrations)


def test_state_schema_docs_match_required_tables() -> None:
    docs = Path("docs/STATE_DB_SCHEMA.md").read_text(encoding="utf-8")
    ddl = _read_state_migrations()

    required = [
        "campaigns",
        "principals",
        "sessions",
        "encounters",
        "intents",
        "map_nodes",
    ]

    for table in required:
        assert f"## {table}" in docs
        assert f"CREATE TABLE IF NOT EXISTS state.{table}" in ddl


def test_state_schema_docs_match_session_fk() -> None:
    docs = Path("docs/STATE_DB_SCHEMA.md").read_text(encoding="utf-8")
    ddl = _read_state_migrations()

    assert "session_id` UUID NOT NULL FK -> sessions(id)" in docs
    assert "encounters_session_id_fkey" in ddl
    assert "intents_session_id_fkey" in ddl
    assert "interventions_session_id_fkey" in ddl
