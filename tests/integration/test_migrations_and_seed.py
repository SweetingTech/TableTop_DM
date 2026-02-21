import psycopg2
import pytest

pytestmark = pytest.mark.integration


def test_seeded_demo_ids_exist(integration_stack, postgres_dsn: str) -> None:
    del integration_stack
    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM state.campaigns WHERE id = '11111111-1111-1111-1111-111111111111'"
            )
            assert cur.fetchone()[0] == 1

            cur.execute(
                "SELECT COUNT(*) FROM state.encounters WHERE id = '55555555-5555-5555-5555-555555555551'"
            )
            assert cur.fetchone()[0] == 1
    finally:
        conn.close()
