"""Campaign lifecycle operations shared by HTTP routes and save import."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from shared.db.connection import transaction


def hard_delete_campaign(campaign_id: str, conn: Any | None = None) -> bool:
    """Delete one campaign root row and rely on schema cascades.

    The ledger schema intentionally stores campaign/session ids without FKs so
    it remains append-only/audit-friendly. Purge/import-replace is the one
    place where those ledger rows are explicitly removed.
    """
    owns_transaction = conn is None
    context = transaction() if owns_transaction else nullcontext(conn)
    deleted = False
    with context as active_conn:
        if active_conn is None:
            raise RuntimeError(
                "campaign lifecycle transaction did not provide a connection"
            )
        with active_conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE state.sessions DISABLE TRIGGER trg_archive_session"
            )
            try:
                cur.execute(
                    "DELETE FROM ledger.session_ledger WHERE campaign_id = %s",
                    (campaign_id,),
                )
                cur.execute(
                    "DELETE FROM state.campaigns WHERE id = %s RETURNING id",
                    (campaign_id,),
                )
                deleted = cur.fetchone() is not None
            finally:
                cur.execute(
                    "ALTER TABLE state.sessions ENABLE TRIGGER trg_archive_session"
                )
    return deleted
