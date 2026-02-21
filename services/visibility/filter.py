import uuid
from typing import Optional
from shared.schemas.contracts import ACTION_REGISTRY


class VisibilityResolver:
    def resolve_visible_to(
        self,
        action_type: str,
        campaign_id: uuid.UUID,
        sender_principal_id: uuid.UUID,
        encounter_id: Optional[uuid.UUID] = None,
        target_entity_id: Optional[uuid.UUID] = None,
    ) -> list[uuid.UUID]:
        entry = ACTION_REGISTRY.get(action_type, {})
        visibility = entry.get("visibility", "all")

        from shared.db.connection import execute_query

        if visibility == "all":
            rows = execute_query(
                "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s",
                (str(campaign_id),),
            )
            return [r["principal_id"] for r in rows]

        elif visibility == "encounter" and encounter_id:
            rows = execute_query(
                """
                SELECT DISTINCT e.controller_principal_id
                FROM state.encounter_slots es
                JOIN state.entities e ON es.entity_id = e.id
                WHERE es.encounter_id = %s AND e.controller_principal_id IS NOT NULL
            """,
                (str(encounter_id),),
            )
            principals = [r["controller_principal_id"] for r in rows]
            dm_rows = execute_query(
                "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s AND role = 'GM'",
                (str(campaign_id),),
            )
            for r in dm_rows:
                if r["principal_id"] not in principals:
                    principals.append(r["principal_id"])
            return principals

        elif visibility == "party":
            rows = execute_query(
                "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s AND role IN ('GM', 'PLAYER')",
                (str(campaign_id),),
            )
            return [r["principal_id"] for r in rows]

        elif visibility == "gods_only":
            rows = execute_query(
                """
                SELECT cm.principal_id
                FROM state.campaign_members cm
                JOIN state.principals p ON cm.principal_id = p.id
                WHERE cm.campaign_id = %s AND (p.principal_type = 'AI_GOD' OR cm.role = 'GM')
            """,
                (str(campaign_id),),
            )
            return [r["principal_id"] for r in rows]

        elif visibility == "proximity":
            rows = execute_query(
                "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s AND role IN ('GM', 'PLAYER')",
                (str(campaign_id),),
            )
            return [r["principal_id"] for r in rows]

        elif visibility == "dm_only":
            rows = execute_query(
                "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s AND role = 'GM'",
                (str(campaign_id),),
            )
            return [r["principal_id"] for r in rows]

        return [sender_principal_id]

    def filter_event_for_principal(
        self, event: dict, principal_id: uuid.UUID
    ) -> Optional[dict]:
        visible_to = event.get("visible_to", [])
        if str(principal_id) in [str(v) for v in visible_to]:
            return event
        return None

    def filter_events_for_principal(
        self, events: list[dict], principal_id: uuid.UUID
    ) -> list[dict]:
        return [e for e in events if self.filter_event_for_principal(e, principal_id)]
