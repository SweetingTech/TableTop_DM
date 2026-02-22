import uuid

import psycopg2
import pytest

from services.orchestrator.pipeline import OrchestratorPipeline, ValidationError
from shared.auth.principal import PrincipalContext
from shared.schemas.contracts import InterventionProposal
from shared.schemas.enums import PrincipalType

pytestmark = pytest.mark.integration


CAMPAIGN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = uuid.UUID("66666666-6666-6666-6666-666666666661")
PLAYER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLAYER_ENTITY_ID = uuid.UUID("33333333-3333-3333-3333-333333333331")


def test_unknown_action_type_rejected_and_warning_logged(
    integration_stack, postgres_dsn: str
) -> None:
    pipeline = OrchestratorPipeline()
    principal = PrincipalContext(
        principal_id=PLAYER_ID,
        principal_type=PrincipalType.HUMAN,
        display_name="PlayerA",
        campaign_id=CAMPAIGN_ID,
        controlled_entity_ids=[PLAYER_ENTITY_ID],
    )
    proposal = InterventionProposal(
        action_type="DO_A_FLIP",
        params={"entity_id": str(PLAYER_ENTITY_ID)},
        proposer_principal_id=PLAYER_ID,
        campaign_id=CAMPAIGN_ID,
        session_id=SESSION_ID,
    )

    with pytest.raises(ValidationError, match="Unknown action_type"):
        pipeline.process_proposal(proposal, principal, SESSION_ID)

    conn = psycopg2.connect(postgres_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT type, payload->'proposal'->>'action_type'
                FROM ledger.session_ledger
                WHERE type = 'SYSTEM_WARNING'
                  AND payload->>'warning' LIKE 'Unknown action_type:%'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "SYSTEM_WARNING"
        assert row[1] == "DO_A_FLIP"
    finally:
        conn.close()


def test_ledger_is_append_only_via_rls(integration_stack, postgres_dsn: str) -> None:
    event_id = uuid.uuid4()
    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger.session_ledger (
                    event_id, event_version, contract_version, type, campaign_id, session_id,
                    sender_principal_id, payload, visible_to, domain_tags, idempotency_key
                ) VALUES (%s, 1, 1, 'STATE_DELTA', %s, %s, %s, '{}'::jsonb, %s::uuid[], %s::text[], %s)
                """,
                (
                    str(event_id),
                    str(CAMPAIGN_ID),
                    str(SESSION_ID),
                    str(PLAYER_ID),
                    [str(PLAYER_ID)],
                    ["integration.append_only"],
                    f"append-only:{event_id}",
                ),
            )

            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(
                    "UPDATE ledger.session_ledger SET payload = '{\"mutated\": true}'::jsonb WHERE event_id = %s",
                    (str(event_id),),
                )
    finally:
        conn.close()


def test_visibility_cannot_be_bypassed_without_principal(
    integration_stack, postgres_dsn: str
) -> None:
    viewer = str(PLAYER_ID)
    hidden = "22222222-2222-2222-2222-222222222223"
    event_id = uuid.uuid4()

    conn = psycopg2.connect(postgres_dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger.session_ledger (
                    event_id, event_version, contract_version, type, campaign_id, session_id,
                    sender_principal_id, payload, visible_to, domain_tags, idempotency_key
                ) VALUES (%s, 1, 1, 'STATE_DELTA', %s, %s, %s, '{}'::jsonb, %s::uuid[], %s::text[], %s)
                """,
                (
                    str(event_id),
                    str(CAMPAIGN_ID),
                    str(SESSION_ID),
                    viewer,
                    [viewer],
                    ["integration.visibility"],
                    f"visibility:{event_id}",
                ),
            )

            cur.execute("RESET app.principal_id")
            cur.execute(
                "SELECT count(*) FROM ledger.session_ledger WHERE event_id = %s",
                (str(event_id),),
            )
            assert cur.fetchone()[0] == 0

            cur.execute("SET app.principal_id = %s", (hidden,))
            cur.execute(
                "SELECT count(*) FROM ledger.session_ledger WHERE event_id = %s",
                (str(event_id),),
            )
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()
