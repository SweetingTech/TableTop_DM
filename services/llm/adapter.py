import os
import json
import uuid
from typing import TYPE_CHECKING, Any, Optional

from shared.schemas.events import EventEnvelope
from shared.schemas.enums import EventType

if TYPE_CHECKING:
    from openai import OpenAI




def get_campaign_ai_config(campaign_id: Optional[uuid.UUID]) -> dict:
    if campaign_id is None:
        return {}
    try:
        from shared.db.connection import execute_one
        row = execute_one("SELECT * FROM state.campaign_settings WHERE campaign_id=%s", (str(campaign_id),))
        return row or {}
    except Exception:
        return {}


def resolve_provider_base_url(provider: str, base_url: Optional[str]) -> Optional[str]:
    provider = (provider or "mock").lower()
    if base_url:
        return base_url
    if provider == "ollama":
        return "http://localhost:11434/v1/"
    if provider == "lmstudio":
        return "http://localhost:1234/v1"
    return None

def get_openai_client() -> "OpenAI":
    from openai import OpenAI

    return OpenAI(
        api_key=os.environ.get(
            "AI_INTEGRATIONS_OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")
        ),
        base_url=os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL", None),
    )


class LLMAdapter:
    def __init__(self, model: str = "gpt-4o-mini", campaign_id: Optional[uuid.UUID] = None, role: str = "dm"):
        self.mode = os.environ.get("TTDM_LLM_MODE", "live").lower()
        cfg = get_campaign_ai_config(campaign_id)
        provider = cfg.get("llm_provider", os.environ.get("AI_PROVIDER", "mock"))
        base_url = resolve_provider_base_url(provider, cfg.get("llm_base_url"))
        self.client: Optional["OpenAI"] = (
            None if self.mode == "mock" or provider == "mock" else get_openai_client()
        )
        if self.client is not None and base_url:
            self.client.base_url = base_url
        self.model = cfg.get("npc_model") if role == "npc" else cfg.get("dm_model", model)
        self.embedding_model = cfg.get("embedding_model", "text-embedding-3-small")
        self.max_retries = 2
        self.timeout = 30

    def _mock_response(self, response_schema: Optional[dict] = None) -> dict:
        properties = (response_schema or {}).get("properties", {})
        if "narration" in properties:
            return {
                "narration": "A deterministic narration describes the resolved outcome."
            }
        if "dialogue" in properties:
            return {
                "dialogue": "Understood. We proceed with caution.",
                "action": "The NPC nods.",
            }
        return {"message": "deterministic mock response"}

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[dict] = None,
    ) -> dict:
        if self.mode == "mock":
            return self._mock_response(response_schema)

        if self.client is None:
            return {"error": "LLM client unavailable"}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        if response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "schema": response_schema,
                    "strict": True,
                },
            }
        else:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                if not content:
                    raise json.JSONDecodeError("Empty response", "", 0)
                parsed = json.loads(content)
                return parsed
            except json.JSONDecodeError:
                if attempt == self.max_retries:
                    return {
                        "error": "Failed to parse LLM JSON response",
                        "raw": content,
                    }
            except Exception as e:
                if attempt == self.max_retries:
                    return {"error": str(e)}

        return {"error": "Max retries exceeded"}

    def list_models(self) -> list[str]:
        if self.mode == "mock" or self.client is None:
            return ["mock-model"]
        models = self.client.models.list()
        return [m.id for m in models.data]

    def embed_texts(self, texts: list[str]) -> dict:
        if self.mode == "mock" or self.client is None:
            vectors = [[float((i + 1) % 7) for i in range(16)] for _ in texts]
            return {"vectors": vectors, "dimensions": 16}
        response = self.client.embeddings.create(model=self.embedding_model, input=texts)
        vectors = [d.embedding for d in response.data]
        dims = len(vectors[0]) if vectors else 0
        return {"vectors": vectors, "dimensions": dims}

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        if self.mode == "mock":
            return "[MockLLM] Deterministic text response."

        if self.client is None:
            return "[LLM Error: client unavailable]"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.8,
                max_tokens=1500,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[LLM Error: {str(e)}]"


class DMNarrationAgent:
    SYSTEM_PROMPT = """You are the Dungeon Master narrator for a tabletop RPG.
Your role is NARRATION ONLY. You describe what happens based on mechanical results you receive.
You NEVER determine mechanical outcomes (damage, hits, saves, etc.) - those are already resolved.
You receive state deltas and roll results, and produce vivid, atmospheric narration.
Respond in JSON format with a single "narration" field containing your narrative text."""

    def __init__(self):
        self.llm = LLMAdapter(role="dm")

    def narrate_event(self, tool_result: dict, context: str = "") -> str:
        prompt = f"""Narrate the following game event result:

Event Data:
{json.dumps(tool_result, indent=2, default=str)}

Context:
{context}

Provide dramatic, atmospheric narration of what happened. Do NOT change any mechanical results."""

        result = self.llm.generate_structured(
            self.SYSTEM_PROMPT,
            prompt,
            response_schema={
                "type": "object",
                "properties": {"narration": {"type": "string"}},
                "required": ["narration"],
                "additionalProperties": False,
            },
        )
        return result.get("narration", result.get("error", "The scene unfolds..."))

    def create_narration_event(
        self,
        narration: str,
        campaign_id: uuid.UUID,
        session_id: uuid.UUID,
        dm_principal_id: uuid.UUID,
        visible_to: list[uuid.UUID],
        encounter_id: Optional[uuid.UUID] = None,
        parent_event_id: Optional[uuid.UUID] = None,
    ) -> EventEnvelope:
        return EventEnvelope(
            type=EventType.NARRATION,
            campaign_id=campaign_id,
            session_id=session_id,
            encounter_id=encounter_id,
            sender_principal_id=dm_principal_id,
            payload={"narration": narration},
            visible_to=visible_to,
            parent_event_id=parent_event_id,
            domain_tags=["narration"],
        )


class NPCDialogueAgent:
    SYSTEM_PROMPT = """You are an NPC in a tabletop RPG world.
You speak in character based on the NPC's personality, emotional state, and context.
You NEVER determine mechanical outcomes.
You only produce dialogue and brief action descriptions.
Respond in JSON with "dialogue" (what the NPC says) and "action" (brief physical action, optional)."""

    def __init__(self):
        self.llm = LLMAdapter(role="npc")

    def generate_dialogue(
        self,
        npc_name: str,
        npc_sheet: dict,
        emotional_state: str,
        context: str,
        speaker_message: str = "",
    ) -> dict:
        prompt = f"""You are {npc_name}.

Your character sheet: {json.dumps(npc_sheet, default=str)}
Current emotional state: {emotional_state}
Scene context: {context}
"""
        if speaker_message:
            prompt += f'\nSomeone says to you: "{speaker_message}"\n'
        prompt += "\nRespond in character."

        result = self.llm.generate_structured(
            self.SYSTEM_PROMPT,
            prompt,
            response_schema={
                "type": "object",
                "properties": {
                    "dialogue": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["dialogue", "action"],
                "additionalProperties": False,
            },
        )
        return result

    def create_dialogue_event(
        self,
        dialogue: dict,
        npc_name: str,
        campaign_id: uuid.UUID,
        session_id: uuid.UUID,
        npc_principal_id: uuid.UUID,
        npc_entity_id: uuid.UUID,
        visible_to: list[uuid.UUID],
        encounter_id: Optional[uuid.UUID] = None,
    ) -> EventEnvelope:
        return EventEnvelope(
            type=EventType.DIALOGUE,
            campaign_id=campaign_id,
            session_id=session_id,
            encounter_id=encounter_id,
            sender_principal_id=npc_principal_id,
            sender_entity_id=npc_entity_id,
            payload={
                "speaker": npc_name,
                "dialogue": dialogue.get("dialogue", ""),
                "action": dialogue.get("action", ""),
            },
            visible_to=visible_to,
            domain_tags=["dialogue", "social"],
        )
