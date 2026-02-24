import uuid
import json
from typing import Optional
from shared.db.connection import get_connection
from shared.schemas.events import EventEnvelope


class LedgerWriter:
    def append_event(self, event: EventEnvelope, conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO ledger.session_ledger (
                    event_id, event_version, contract_version, type,
                    campaign_id, session_id, encounter_id,
                    sender_principal_id, sender_entity_id,
                    payload, visible_to, parent_event_id,
                    domain_tags, idempotency_key
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s, %s
                )
                ON CONFLICT (session_id, sender_principal_id, idempotency_key)
                DO UPDATE SET
                    idempotency_key = EXCLUDED.idempotency_key
                RETURNING seq_id, event_id, (xmax = 0) AS inserted
            """,
                (
                    str(event.event_id),
                    event.event_version,
                    event.contract_version,
                    event.type.value,
                    str(event.campaign_id),
                    str(event.session_id),
                    str(event.encounter_id) if event.encounter_id else None,
                    str(event.sender_principal_id),
                    str(event.sender_entity_id) if event.sender_entity_id else None,
                    json.dumps(event.payload),
                    [str(v) for v in event.visible_to],
                    str(event.parent_event_id) if event.parent_event_id else None,
                    event.domain_tags,
                    event.idempotency_key,
                ),
            )

            row = cur.fetchone()
            if own_conn:
                conn.commit()

            if row:
                inserted = bool(row[2])
                result = {
                    "seq_id": row[0],
                    "event_id": str(row[1]),
                    "inserted": inserted,
                }
                if not inserted:
                    result["reason"] = "idempotency_key_duplicate"
                return result
            return {"inserted": False, "reason": "ledger_insert_failed"}

        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            cur.close()
            if own_conn:
                conn.close()

    def read_events(
        self,
        session_id: uuid.UUID,
        principal_id: uuid.UUID,
        from_seq: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL app.principal_id = %s", (str(principal_id),))
            cur.execute(
                """
                SELECT seq_id, event_id, type, sender_principal_id, sender_entity_id,
                       payload, domain_tags, created_at, parent_event_id
                FROM ledger.session_ledger
                WHERE session_id = %s AND seq_id > %s
                ORDER BY seq_id ASC
                LIMIT %s
            """,
                (str(session_id), from_seq, limit),
            )

            columns = [desc[0] for desc in cur.description]
            rows = []
            for row in cur.fetchall():
                rows.append(dict(zip(columns, row)))
            conn.commit()
            return rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def write_summary(
        self,
        campaign_id: uuid.UUID,
        session_id: uuid.UUID,
        scope: str,
        principal_id: Optional[uuid.UUID],
        from_seq: int,
        to_seq: int,
        summary_text: str,
        visible_to: list[uuid.UUID],
        conn=None,
    ) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            summary_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO ledger.session_summaries (
                    id, campaign_id, session_id, summary_scope,
                    principal_id, from_seq_id, to_seq_id,
                    summary_text, visible_to
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::uuid[])
                RETURNING id
            """,
                (
                    str(summary_id),
                    str(campaign_id),
                    str(session_id),
                    scope,
                    str(principal_id) if principal_id else None,
                    from_seq,
                    to_seq,
                    summary_text,
                    [str(v) for v in visible_to],
                ),
            )

            row = cur.fetchone()
            if own_conn:
                conn.commit()
            return {"summary_id": str(row[0])}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            cur.close()
            if own_conn:
                conn.close()
