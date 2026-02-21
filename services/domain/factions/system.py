import uuid
import json
from typing import Optional
from shared.db.connection import execute_query, execute_one, get_connection
from shared.schemas.events import StateDelta


class FactionSystem:

    def create_faction(self, campaign_id: uuid.UUID, name: str,
                       description: str = "", tenets: list[str] = None,
                       conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            faction_id = uuid.uuid4()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO state.factions (id, campaign_id, name, description, tenets)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (str(faction_id), str(campaign_id), name, description,
                  json.dumps(tenets or [])))

            if own_conn:
                conn.commit()
            cur.close()
            return {"faction_id": str(faction_id), "name": name}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def join_faction(self, entity_id: uuid.UUID, faction_id: uuid.UUID,
                     rank: str = "MEMBER", conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO state.faction_memberships (faction_id, entity_id, rank, joined_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (faction_id, entity_id) DO UPDATE SET rank = EXCLUDED.rank
            """, (str(faction_id), str(entity_id), rank))

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "entity_id": str(entity_id), "faction_id": str(faction_id)}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def leave_faction(self, entity_id: uuid.UUID, faction_id: uuid.UUID,
                      conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM state.faction_memberships
                WHERE faction_id = %s AND entity_id = %s
            """, (str(faction_id), str(entity_id)))

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "left_faction": str(faction_id)}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def declare_war(self, campaign_id: uuid.UUID, faction_a_id: uuid.UUID,
                    faction_b_id: uuid.UUID, conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO state.faction_wars (campaign_id, faction_a_id, faction_b_id, status, started_at)
                VALUES (%s, %s, %s, 'ACTIVE', now())
                ON CONFLICT (campaign_id, faction_a_id, faction_b_id) DO UPDATE SET status = 'ACTIVE'
            """, (str(campaign_id), str(faction_a_id), str(faction_b_id)))

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "war_declared": True}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def check_tenet_violation(self, entity_id: uuid.UUID, action_tags: list[str],
                              campaign_id: uuid.UUID) -> list[dict]:
        memberships = execute_query("""
            SELECT f.id, f.name, f.tenets, fm.rank
            FROM state.faction_memberships fm
            JOIN state.factions f ON fm.faction_id = f.id
            WHERE fm.entity_id = %s AND f.campaign_id = %s
        """, (str(entity_id), str(campaign_id)))

        violations = []
        for m in memberships:
            tenets = m.get("tenets", [])
            if isinstance(tenets, str):
                try:
                    tenets = json.loads(tenets)
                except Exception:
                    tenets = []

            for tenet in tenets:
                if isinstance(tenet, dict):
                    forbidden_tags = tenet.get("forbidden_tags", [])
                    for tag in action_tags:
                        if tag in forbidden_tags:
                            violations.append({
                                "faction_id": str(m["id"]),
                                "faction_name": m["name"],
                                "tenet_violated": tenet.get("name", "unknown"),
                                "trigger_tag": tag,
                                "consequences": tenet.get("consequences", []),
                            })

        return violations

    def apply_tenet_consequences(self, violations: list[dict],
                                 entity_id: uuid.UUID,
                                 campaign_id: uuid.UUID) -> list[StateDelta]:
        deltas = []
        for v in violations:
            for consequence in v.get("consequences", []):
                if consequence == "REVOKE_SPELL_ACCESS":
                    deltas.append(StateDelta(
                        table="state.entities",
                        operation="UPDATE",
                        entity_id=entity_id,
                        changes={"spell_access_revoked": True, "faction": v["faction_name"]},
                        domain_tags=["tenet_violation", "spell_revoke"],
                    ))
                elif consequence == "APPLY_CURSE":
                    deltas.append(StateDelta(
                        table="state.conditions",
                        operation="INSERT",
                        entity_id=entity_id,
                        changes={"condition_type": "CURSED", "source": f"tenet_violation:{v['faction_name']}"},
                        domain_tags=["tenet_violation", "curse"],
                    ))
                elif consequence == "SET_BOUNTY":
                    deltas.append(StateDelta(
                        table="state.bounties",
                        operation="INSERT",
                        entity_id=entity_id,
                        changes={
                            "faction_id": v["faction_id"],
                            "reason": f"Tenet violation: {v['tenet_violated']}",
                        },
                        domain_tags=["tenet_violation", "bounty"],
                    ))
        return deltas
