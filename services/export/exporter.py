import uuid
import json
from datetime import datetime
from shared.db.connection import execute_query, get_connection


class SessionExporter:
    def export_to_markdown(
        self, session_id: uuid.UUID, principal_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> str:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL app.principal_id = %s", (str(principal_id),))

            import psycopg2.extras

            dict_cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            dict_cur.execute("SET LOCAL app.principal_id = %s", (str(principal_id),))
            dict_cur.execute(
                """
                SELECT sl.*, p.display_name as sender_name
                FROM ledger.session_ledger sl
                LEFT JOIN state.principals p ON sl.sender_principal_id = p.id
                WHERE sl.session_id = %s
                ORDER BY sl.seq_id ASC
            """,
                (str(session_id),),
            )
            events = dict_cur.fetchall()

            campaign = None
            import psycopg2.extras

            c2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            c2.execute(
                "SELECT name FROM state.campaigns WHERE id = %s", (str(campaign_id),)
            )
            row = c2.fetchone()
            if row:
                campaign = row

            conn.commit()
            dict_cur.close()
            c2.close()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        lines = []
        campaign_name = campaign["name"] if campaign else "Unknown Campaign"
        lines.append(f"# Session Log: {campaign_name}")
        lines.append(f"**Session ID:** `{session_id}`")
        lines.append(
            f"**Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
        lines.append(f"**Events:** {len(events)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        for event in events:
            event_type = event.get("type", "UNKNOWN")
            sender = event.get("sender_name", "Unknown")
            payload = event.get("payload", {})
            timestamp = event.get("created_at", "")
            if hasattr(timestamp, "strftime"):
                timestamp = timestamp.strftime("%H:%M:%S")

            if event_type == "NARRATION":
                narration = payload.get("narration", "")
                lines.append(f"*{narration}*")
                lines.append("")

            elif event_type == "DIALOGUE":
                speaker = payload.get("speaker", sender)
                dialogue = payload.get("dialogue", "")
                action = payload.get("action", "")
                lines.append(f'**{speaker}:** "{dialogue}"')
                if action:
                    lines.append(f"*{action}*")
                lines.append("")

            elif event_type == "CHAT":
                speaker = payload.get("speaker", sender)
                message = payload.get("message", "")
                channel = payload.get("channel", "")
                prefix = f"[{channel}] " if channel else ""
                lines.append(f"{prefix}**{speaker}:** {message}")
                lines.append("")

            elif event_type == "TOOL_CALL":
                tool = payload.get("tool_name", "unknown")
                result = payload.get("result", {})
                rolls = payload.get("rolls", [])

                lines.append(f"### {tool.replace('_', ' ').title()} [{timestamp}]")
                if rolls:
                    for r in rolls:
                        lines.append(f"- Roll: {r.get('breakdown', '')}")
                if isinstance(result, dict):
                    for k, v in result.items():
                        if k not in ("rolls",):
                            lines.append(f"- {k}: {v}")
                lines.append("")

            elif event_type == "STATE_DELTA":
                deltas = payload.get("deltas", [])
                for d in deltas:
                    tags = ", ".join(d.get("domain_tags", []))
                    lines.append(f"> State change: {d.get('table', '')} [{tags}]")
                lines.append("")

            elif event_type == "SYSTEM_WARNING":
                warning = payload.get("warning", "")
                lines.append(f"> **WARNING:** {warning}")
                lines.append("")

            else:
                lines.append(
                    f"[{event_type}] {sender}: {json.dumps(payload, default=str)[:200]}"
                )
                lines.append("")

        return "\n".join(lines)


class ReplayEngine:
    def load_checkpoint(self, session_id: uuid.UUID, up_to_seq: int) -> dict:
        events = execute_query(
            """
            SELECT * FROM ledger.session_ledger
            WHERE session_id = %s AND seq_id <= %s
            ORDER BY seq_id ASC
        """,
            (str(session_id), up_to_seq),
        )

        return {
            "session_id": str(session_id),
            "event_count": len(events),
            "events": [dict(e) for e in events],
            "last_seq": up_to_seq,
        }

    def replay_deltas(self, events: list[dict]) -> list[dict]:
        state_changes = []
        for event in events:
            if event.get("type") == "STATE_DELTA":
                payload = event.get("payload", {})
                deltas = payload.get("deltas", [])
                for d in deltas:
                    state_changes.append(
                        {
                            "seq_id": event.get("seq_id"),
                            "table": d.get("table"),
                            "operation": d.get("operation"),
                            "entity_id": d.get("entity_id"),
                            "changes": d.get("changes", {}),
                        }
                    )
        return state_changes

    def verify_state(self, session_id: uuid.UUID, expected_state: dict) -> dict:
        checkpoint = self.load_checkpoint(session_id, up_to_seq=999999999)
        replayed = self.replay_deltas(checkpoint["events"])

        entity_ids = [str(entity_id) for entity_id in expected_state]
        actual_entities = {}
        if entity_ids:
            results = execute_query(
                "SELECT id, hp_current, hp_max, ac "
                "FROM state.entities WHERE id = ANY(%s::uuid[])",
                (entity_ids,),
            )
            for row in results:
                actual_entities[str(row["id"])] = row

        mismatches = []
        for entity_id, expected in expected_state.items():
            actual = actual_entities.get(str(entity_id))
            if actual:
                for field, exp_val in expected.items():
                    act_val = actual.get(field)
                    if act_val != exp_val:
                        mismatches.append(
                            {
                                "entity_id": entity_id,
                                "field": field,
                                "expected": exp_val,
                                "actual": act_val,
                            }
                        )

        return {
            "session_id": str(session_id),
            "deltas_replayed": len(replayed),
            "mismatches": mismatches,
            "verified": len(mismatches) == 0,
        }
