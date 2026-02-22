from pathlib import Path

import pytest

pytestmark = pytest.mark.contracts


def test_state_schema_docs_match_required_tables() -> None:
    docs = Path("docs/STATE_DB_SCHEMA.md").read_text(encoding="utf-8")
    ddl = Path("infra/sql/migrations/001_state_schema.sql").read_text(encoding="utf-8")

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
    ddl = Path("infra/sql/migrations/001_state_schema.sql").read_text(encoding="utf-8")

    assert "session_id` UUID NOT NULL FK -> sessions(id)" in docs
    assert "session_id uuid NOT NULL REFERENCES state.sessions(id)" in ddl
