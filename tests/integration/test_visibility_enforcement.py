import uuid

import psycopg2
import pytest

pytestmark = pytest.mark.integration


def test_ledger_row_level_visibility_filtering(
    integration_stack, postgres_dsn: str
) -> None:
    del integration_stack
    event_id = uuid.uuid4()
    viewer = "22222222-2222-2222-2222-222222222222"
    hidden_viewer = "22222222-2222-2222-2222-222222222223"

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger.session_ledger (
                    event_id,
                    event_version,
                    contract_version,
                    type,
                    campaign_id,
                    session_id,
                    sender_principal_id,
                    payload,
                    visible_to,
                    domain_tags,
                    idempotency_key
                ) VALUES (%s, 1, 1, 'STATE_DELTA', %s, %s, %s, '{}'::jsonb, %s::uuid[], %s::text[], %s)
                """,
                (
                    str(event_id),
                    "11111111-1111-1111-1111-111111111111",
                    "66666666-6666-6666-6666-666666666661",
                    viewer,
                    [viewer],
                    ["combat.damage"],
                    f"integration:{event_id}",
                ),
            )

            cur.execute("SET app.principal_id = %s", (viewer,))
            cur.execute(
                "SELECT count(*) FROM ledger.session_ledger WHERE event_id = %s",
                (str(event_id),),
            )
            assert cur.fetchone()[0] == 1

            cur.execute("SET app.principal_id = %s", (hidden_viewer,))
            cur.execute(
                "SELECT count(*) FROM ledger.session_ledger WHERE event_id = %s",
                (str(event_id),),
            )
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()
