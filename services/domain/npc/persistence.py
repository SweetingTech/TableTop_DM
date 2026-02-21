import uuid
import json
from typing import Optional
from shared.db.connection import execute_query, execute_one, get_connection
from shared.schemas.events import StateDelta, EventEnvelope
from shared.schemas.enums import EventType


class NPCPersistence:

    def instantiate_npc(self, campaign_id: uuid.UUID, location_entity_id: uuid.UUID,
                        npc_template: dict, conn=None) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            npc_id = uuid.uuid4()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO state.entities (
                    id, campaign_id, entity_type, name, tags,
                    public_sheet, secret_sheet,
                    hp_current, hp_max, ac, speed,
                    controlled_by, controller_principal_id
                ) VALUES (%s, %s, 'NPC', %s, %s, %s, %s, %s, %s, %s, %s, 'AI_NPC', %s)
                RETURNING id
            """, (
                str(npc_id), str(campaign_id),
                npc_template.get("name", "Unknown NPC"),
                npc_template.get("tags", ["npc"]),
                json.dumps(npc_template.get("public_sheet", {})),
                json.dumps(npc_template.get("secret_sheet", {})),
                npc_template.get("hp", 10), npc_template.get("hp", 10),
                npc_template.get("ac", 10), npc_template.get("speed", 30),
                npc_template.get("controller_principal_id"),
            ))

            if own_conn:
                conn.commit()
            cur.close()
            return {"npc_id": str(npc_id), "name": npc_template.get("name"), "instantiated": True}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def get_location_npcs(self, campaign_id: uuid.UUID,
                          location_entity_id: uuid.UUID) -> list[dict]:
        rows = execute_query("""
            SELECT id, name, public_sheet, hp_current, hp_max
            FROM state.entities
            WHERE campaign_id = %s AND entity_type = 'NPC' AND hp_current > 0
        """, (str(campaign_id),))
        return [dict(r) for r in rows]


class ConsequenceEngine:

    def record_death(self, entity_id: uuid.UUID, killer_entity_id: Optional[uuid.UUID],
                     campaign_id: uuid.UUID, location: str = "unknown",
                     witnesses: list[uuid.UUID] = None,
                     conn=None) -> list[StateDelta]:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()

            cur.execute("""
                UPDATE state.entities
                SET hp_current = 0,
                    secret_sheet = jsonb_set(
                        secret_sheet,
                        '{death_record}',
                        %s::jsonb
                    ),
                    updated_at = now()
                WHERE id = %s
            """, (
                json.dumps({
                    "killer": str(killer_entity_id) if killer_entity_id else None,
                    "location": location,
                    "witnesses": [str(w) for w in (witnesses or [])],
                }),
                str(entity_id),
            ))

            if own_conn:
                conn.commit()
            cur.close()
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

        return self._generate_consequences(
            entity_id, killer_entity_id, campaign_id, witnesses or []
        )

    def _generate_consequences(self, entity_id: uuid.UUID,
                               killer_entity_id: Optional[uuid.UUID],
                               campaign_id: uuid.UUID,
                               witnesses: list[uuid.UUID]) -> list[StateDelta]:
        consequences = []

        if killer_entity_id:
            consequences.append(StateDelta(
                table="state.bounties",
                operation="INSERT",
                entity_id=killer_entity_id,
                changes={
                    "reason": "murder",
                    "victim_entity_id": str(entity_id),
                    "campaign_id": str(campaign_id),
                },
                domain_tags=["murder", "bounty", "justice"],
            ))

        if witnesses:
            consequences.append(StateDelta(
                table="state.entities",
                operation="UPDATE",
                entity_id=entity_id,
                changes={"rumor_propagation": True, "witness_count": len(witnesses)},
                domain_tags=["rumor", "death", "social"],
            ))

        consequences.append(StateDelta(
            table="state.location_metrics",
            operation="UPDATE",
            entity_id=entity_id,
            changes={"stability_delta": -5},
            domain_tags=["instability", "death"],
        ))

        return consequences
