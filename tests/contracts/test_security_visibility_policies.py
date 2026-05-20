from pathlib import Path

import pytest

pytestmark = pytest.mark.contracts


def test_ledger_policy_is_insert_only_for_service_writes() -> None:
    sql = Path("infra/sql/migrations/003_security_visibility.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE POLICY session_ledger_service_write" in sql
    assert "ON ledger.session_ledger" in sql
    assert "FOR INSERT" in sql
    assert "FOR UPDATE" not in sql
    assert "FOR DELETE" not in sql


def test_visibility_policy_requires_matching_principal() -> None:
    sql = Path("infra/sql/migrations/003_security_visibility.sql").read_text(
        encoding="utf-8"
    )

    assert "NULLIF(current_setting('app.principal_id', true), '') IS NOT NULL" in sql
    assert (
        "NULLIF(current_setting('app.principal_id', true), '')::uuid = ANY(visible_to)"
        in sql
    )
