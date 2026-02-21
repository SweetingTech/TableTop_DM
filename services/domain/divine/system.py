import uuid
from typing import Optional
from shared.db.connection import execute_query, execute_one, get_connection
from shared.schemas.events import StateDelta


DEFAULT_AP_PER_SESSION = 10
DEFAULT_AP_PER_ENCOUNTER = 5


class DivineAPSystem:

    def get_god_ap(self, god_entity_id: uuid.UUID, campaign_id: uuid.UUID) -> dict:
        row = execute_one("""
            SELECT e.id, e.name, e.public_sheet
            FROM state.entities e
            WHERE e.id = %s AND e.campaign_id = %s
        """, (str(god_entity_id), str(campaign_id)))

        if not row:
            return {"error": "God entity not found"}

        sheet = row.get("public_sheet", {})
        return {
            "god_id": str(row["id"]),
            "god_name": row["name"],
            "ap_current": sheet.get("divine_ap", DEFAULT_AP_PER_SESSION),
            "ap_max_session": sheet.get("ap_max_session", DEFAULT_AP_PER_SESSION),
            "ap_max_encounter": sheet.get("ap_max_encounter", DEFAULT_AP_PER_ENCOUNTER),
            "ap_used_encounter": sheet.get("ap_used_encounter", 0),
            "ap_used_session": sheet.get("ap_used_session", 0),
        }

    def deduct_divine_ap(self, god_entity_id: uuid.UUID, ap_cost: int,
                          campaign_id: uuid.UUID, conn=None) -> dict:
        info = self.get_god_ap(god_entity_id, campaign_id)
        if "error" in info:
            return info

        if info["ap_current"] < ap_cost:
            return {"success": False, "reason": "Insufficient divine AP"}

        session_remaining = info["ap_max_session"] - info["ap_used_session"]
        encounter_remaining = info["ap_max_encounter"] - info["ap_used_encounter"]

        if ap_cost > session_remaining:
            return {"success": False, "reason": "Session AP cap exceeded"}
        if ap_cost > encounter_remaining:
            return {"success": False, "reason": "Encounter AP cap exceeded"}

        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE state.entities
                SET public_sheet = jsonb_set(
                    jsonb_set(
                        jsonb_set(
                            public_sheet,
                            '{divine_ap}', to_jsonb(COALESCE((public_sheet->>'divine_ap')::int, %s) - %s)
                        ),
                        '{ap_used_session}', to_jsonb(COALESCE((public_sheet->>'ap_used_session')::int, 0) + %s)
                    ),
                    '{ap_used_encounter}', to_jsonb(COALESCE((public_sheet->>'ap_used_encounter')::int, 0) + %s)
                ),
                updated_at = now()
                WHERE id = %s
            """, (DEFAULT_AP_PER_SESSION, ap_cost, ap_cost, ap_cost, str(god_entity_id)))

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "ap_deducted": ap_cost}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def reset_encounter_ap(self, campaign_id: uuid.UUID, conn=None) -> int:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE state.entities
                SET public_sheet = jsonb_set(public_sheet, '{ap_used_encounter}', '0'::jsonb),
                    updated_at = now()
                WHERE campaign_id = %s AND controlled_by = 'AI_GOD'
            """, (str(campaign_id),))
            count = cur.rowcount
            if own_conn:
                conn.commit()
            cur.close()
            return count
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()


class AuthoritySystem:

    AUTHORITY_RANKS = {
        "ELDER": 3,
        "GREATER": 2,
        "LESSER": 1,
        "MINOR": 0,
    }

    def get_authority_rank(self, god_entity_id: uuid.UUID) -> int:
        row = execute_one(
            "SELECT public_sheet FROM state.entities WHERE id = %s",
            (str(god_entity_id),)
        )
        if not row:
            return 0
        sheet = row.get("public_sheet", {})
        rank_name = sheet.get("authority_rank", "MINOR")
        return self.AUTHORITY_RANKS.get(rank_name, 0)

    def can_override(self, overrider_id: uuid.UUID, target_id: uuid.UUID) -> dict:
        overrider_rank = self.get_authority_rank(overrider_id)
        target_rank = self.get_authority_rank(target_id)

        can = overrider_rank > target_rank
        return {
            "can_override": can,
            "overrider_rank": overrider_rank,
            "target_rank": target_rank,
            "reason": "Higher authority can override" if can else "Insufficient authority rank",
        }

    def resolve_divine_conflict(self, interventions: list[dict]) -> list[dict]:
        sorted_interventions = sorted(
            interventions, key=lambda i: i.get("authority_rank", 0), reverse=True
        )

        resolved = []
        for i, intervention in enumerate(sorted_interventions):
            overridden = False
            for higher in sorted_interventions[:i]:
                if higher.get("authority_rank", 0) > intervention.get("authority_rank", 0):
                    if higher.get("target_entity_id") == intervention.get("target_entity_id"):
                        overridden = True
                        break

            intervention["overridden"] = overridden
            resolved.append(intervention)

        return resolved


class GrudgeTracker:

    def record_grudge(self, god_a_id: uuid.UUID, god_b_id: uuid.UUID,
                      reason: str, campaign_id: uuid.UUID, conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE state.entities
                SET public_sheet = jsonb_set(
                    public_sheet,
                    '{grudges}',
                    COALESCE(public_sheet->'grudges', '[]'::jsonb) || %s::jsonb
                ),
                updated_at = now()
                WHERE id = %s
            """, (
                f'[{{"target": "{god_b_id}", "reason": "{reason}"}}]',
                str(god_a_id),
            ))
            if own_conn:
                conn.commit()
            cur.close()
            return {"recorded": True, "god_a": str(god_a_id), "god_b": str(god_b_id)}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()
