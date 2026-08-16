import uuid
from typing import Optional
from shared.schemas.events import EventEnvelope
from shared.schemas.enums import EventType
from shared.db.connection import execute_query, execute_one
from services.llm.adapter import LLMAdapter, DMNarrationAgent, NPCDialogueAgent
from services.ledger.writer import LedgerWriter
from services.visibility.filter import VisibilityResolver


class ConversationManager:
    def __init__(self, campaign_id: Optional[uuid.UUID] = None):
        self.campaign_id = campaign_id
        self.llm = LLMAdapter(campaign_id=campaign_id)
        self.dm_agent = DMNarrationAgent(campaign_id=campaign_id)
        self.npc_agent = NPCDialogueAgent(campaign_id=campaign_id)
        self.ledger = LedgerWriter()
        self.visibility = VisibilityResolver()

    def handle_olympus_chat(
        self, campaign_id: uuid.UUID, session_id: uuid.UUID, trigger_event: dict
    ) -> list[EventEnvelope]:
        gods = execute_query(
            """
            SELECT p.id, p.display_name, e.id as entity_id, e.name, e.public_sheet
            FROM state.principals p
            JOIN state.campaign_members cm ON p.id = cm.principal_id
            LEFT JOIN state.entities e ON e.controller_principal_id = p.id AND e.campaign_id = %s
            WHERE cm.campaign_id = %s AND p.principal_type = 'AI_GOD' AND p.is_active = true
        """,
            (str(campaign_id), str(campaign_id)),
        )

        if not gods:
            return []

        god_ids = [g["id"] for g in gods]
        dm_rows = execute_query(
            "SELECT principal_id FROM state.campaign_members WHERE campaign_id = %s AND role = 'GM'",
            (str(campaign_id),),
        )
        visible_to = god_ids + [r["principal_id"] for r in dm_rows]

        events = []
        for god in gods:
            prompt = f"""You are {god["name"]}, a deity observing mortal affairs.
React to this event from the divine perspective. Keep it brief (1-2 sentences).
Respond in JSON with "reaction" field."""

            result = self.llm.generate_structured(
                "You are a god in an Olympus chat channel. React to mortal events briefly and in character.",
                prompt,
                response_schema={
                    "type": "object",
                    "properties": {"reaction": {"type": "string"}},
                    "required": ["reaction"],
                    "additionalProperties": False,
                },
            )

            event = EventEnvelope(
                type=EventType.CHAT,
                campaign_id=campaign_id,
                session_id=session_id,
                sender_principal_id=god["id"],
                sender_entity_id=god.get("entity_id"),
                payload={
                    "channel": "olympus",
                    "speaker": god["name"],
                    "message": result.get("reaction", "..."),
                },
                visible_to=visible_to,
                domain_tags=["divine", "olympus"],
            )
            events.append(event)

        return events

    def handle_proximity_chat(
        self,
        campaign_id: uuid.UUID,
        session_id: uuid.UUID,
        speaker_entity_id: uuid.UUID,
        speaker_principal_id: uuid.UUID,
        message: str,
        target_entity_id: Optional[uuid.UUID] = None,
    ) -> list[EventEnvelope]:
        events = []

        visible_to = self.visibility.resolve_visible_to(
            "TALK", campaign_id, speaker_principal_id
        )

        speaker = execute_one(
            "SELECT name FROM state.entities WHERE id = %s", (str(speaker_entity_id),)
        )
        speaker_name = speaker["name"] if speaker else "Unknown"

        chat_event = EventEnvelope(
            type=EventType.CHAT,
            campaign_id=campaign_id,
            session_id=session_id,
            sender_principal_id=speaker_principal_id,
            sender_entity_id=speaker_entity_id,
            payload={
                "channel": "proximity",
                "speaker": speaker_name,
                "message": message,
                "target_entity_id": str(target_entity_id) if target_entity_id else None,
            },
            visible_to=visible_to,
            domain_tags=["social", "dialogue"],
        )
        events.append(chat_event)

        if target_entity_id:
            target = execute_one(
                """
                SELECT e.*, p.id as principal_id, p.principal_type
                FROM state.entities e
                LEFT JOIN state.principals p ON e.controller_principal_id = p.id
                WHERE e.id = %s
            """,
                (str(target_entity_id),),
            )

            if target and target.get("principal_type") in ("AI_NPC", "AI_GOD"):
                npc_sheet = target.get("public_sheet", {})
                dialogue = self.npc_agent.generate_dialogue(
                    npc_name=target["name"],
                    npc_sheet=npc_sheet,
                    emotional_state="neutral",
                    context=f"In {campaign_id}",
                    speaker_message=message,
                )

                reply_event = self.npc_agent.create_dialogue_event(
                    dialogue=dialogue,
                    npc_name=target["name"],
                    campaign_id=campaign_id,
                    session_id=session_id,
                    npc_principal_id=target["principal_id"],
                    npc_entity_id=target_entity_id,
                    visible_to=visible_to,
                )
                events.append(reply_event)

        return events

    def handle_offscreen_simulation(
        self, campaign_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[dict]:
        npcs = execute_query(
            """
            SELECT e.id, e.name, e.public_sheet, e.tags
            FROM state.entities e
            WHERE e.campaign_id = %s AND e.controlled_by = 'AI_NPC'
              AND e.hp_current > 0
        """,
            (str(campaign_id),),
        )

        deltas = []
        for npc in npcs:
            tags = npc.get("tags", [])
            if "offscreen" in tags:
                deltas.append(
                    {
                        "entity_id": str(npc["id"]),
                        "entity_name": npc["name"],
                        "type": "offscreen_tick",
                        "changes": {},
                    }
                )

        return deltas
