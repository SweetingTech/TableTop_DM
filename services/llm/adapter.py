import os
import json
import uuid
import logging
from typing import TYPE_CHECKING, Any, Optional, cast

from shared.schemas.events import EventEnvelope
from shared.schemas.enums import EventType

if TYPE_CHECKING:
    from openai import OpenAI


def get_campaign_ai_config(campaign_id: Optional[uuid.UUID]) -> dict:
    if campaign_id is None:
        return {}
    try:
        from shared.db.connection import execute_one

        row = execute_one(
            "SELECT * FROM state.campaign_settings WHERE campaign_id=%s",
            (str(campaign_id),),
        )
        return row or {}
    except Exception:
        logging.exception(
            "Failed to retrieve campaign AI config for campaign_id=%s", campaign_id
        )
        return {}


PROVIDER_DEFAULTS = {
    # Local
    "ollama": "http://localhost:11434/v1/",
    "lmstudio": "http://localhost:1234/v1",
    # Hosted, OpenAI-compatible
    "openai": None,  # SDK default
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    # Hosted, Anthropic-native (separate SDK path; base_url not used by OpenAI SDK)
    "anthropic": "https://api.anthropic.com",
    "mock": None,
}

# Keep this in sync with the providers the API/UI offers.
SUPPORTED_PROVIDERS = set(PROVIDER_DEFAULTS.keys())

EMBEDDING_MODEL_DEFAULTS = {
    "openai": "text-embedding-3-small",
    "ollama": "nomic-embed-text",
    "mock": "mock-embedding-16",
}

EMBEDDING_MODEL_HINTS = ("embed", "embedding", "nomic", "bge", "e5")


def resolve_provider_base_url(provider: str, base_url: Optional[str]) -> Optional[str]:
    provider = (provider or "mock").lower()
    if base_url:
        return base_url
    return PROVIDER_DEFAULTS.get(provider)


def select_embedding_model(
    provider: str,
    configured: Optional[str] = None,
    available_models: Optional[list[str]] = None,
) -> Optional[str]:
    provider = (provider or "mock").lower()
    configured = (configured or "").strip()
    if configured:
        if (
            provider in {"lmstudio", "ollama"}
            and configured == "text-embedding-3-small"
        ):
            return EMBEDDING_MODEL_DEFAULTS.get(provider)
        return configured
    if provider == "lmstudio":
        for model in available_models or []:
            low = model.lower()
            if any(hint in low for hint in EMBEDDING_MODEL_HINTS):
                return model
        return None
    return EMBEDDING_MODEL_DEFAULTS.get(provider)


def _resolve_api_key(provider: str, cfg: dict) -> str:
    """Pull the API key for the LLM provider from (in priority):
    campaign.api_keys → global_settings.api_keys → environment variable.
    Decrypts vault-encrypted values."""
    from services.saves.vault import decrypt_str
    from shared.db.connection import execute_one

    settings = (cfg or {}).get("settings") or {}
    if isinstance(settings, str):
        try:
            import json as _json

            settings = _json.loads(settings)
        except Exception:
            settings = {}

    keys = settings.get("api_keys") or {}
    raw = keys.get(provider)

    if not raw:
        try:
            row = execute_one(
                "SELECT value FROM state.global_settings WHERE key = 'api_keys'"
            )
            gkeys = (row or {}).get("value") or {}
            if isinstance(gkeys, str):
                import json as _json

                gkeys = _json.loads(gkeys)
            raw = gkeys.get(provider)
        except Exception:
            raw = None

    if raw:
        return decrypt_str(raw)
    if provider in {"lmstudio", "ollama", "mock"}:
        # OpenAI-compatible local servers still require the SDK field to be
        # non-empty even though they do not authenticate requests.
        return "local-provider"
    # Environment fallback for ops setups (e.g. shipping a key via .env).
    return cast(
        str,
        os.environ.get(f"{provider.upper()}_API_KEY")
        or os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY", ""),
    )


def get_openai_client(provider: str = "openai", cfg: Optional[dict] = None) -> "OpenAI":
    from openai import OpenAI

    return OpenAI(
        api_key=_resolve_api_key(provider, cfg or {}),
        base_url=os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL", None),
    )


class LLMAdapter:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        campaign_id: Optional[uuid.UUID] = None,
        role: str = "dm",
    ):
        self.mode = os.environ.get("TTDM_LLM_MODE", "live").lower()
        cfg = get_campaign_ai_config(campaign_id)
        provider = cfg.get("llm_provider", os.environ.get("AI_PROVIDER", "mock"))
        base_url = resolve_provider_base_url(provider, cfg.get("llm_base_url"))
        self.client: Optional["OpenAI"] = (
            None
            if self.mode == "mock" or provider == "mock"
            else get_openai_client(provider=provider, cfg=cfg)
        )
        if self.client is not None and base_url:
            self.client.base_url = base_url  # type: ignore[assignment]
        default_model = model
        if role == "npc":
            self.model = cfg.get("npc_model") or default_model
        else:
            self.model = cfg.get("dm_model") or default_model
        self.embedding_model = select_embedding_model(
            provider, cfg.get("embedding_model")
        )
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
        if not self.embedding_model:
            raise ValueError("embedding_model_required")
        response = self.client.embeddings.create(
            model=self.embedding_model, input=texts
        )
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
When CAMPAIGN LORE CONTEXT is provided, weave it in naturally — do NOT invent facts beyond it.
Respond in JSON format with a single "narration" field containing your narrative text."""

    def __init__(self, campaign_id: Optional[uuid.UUID] = None):
        self.campaign_id = campaign_id
        self.llm = LLMAdapter(role="dm", campaign_id=campaign_id)

    def narrate_event(
        self,
        tool_result: dict,
        context: str = "",
        *,
        session_id: Optional[uuid.UUID] = None,
        return_citations: bool = False,
    ) -> str | dict[str, Any]:
        """Generate narration. When `session_id` is provided, the DM
        retrieves the campaign's RAG context (lore docs uploaded via the
        Knowledge Base tab) tagged for dm_narration purpose and injects
        the top chunks into the prompt before generation. Visibility
        filter restricts to public/party/dm_only — DM narration is
        DM-visible by definition."""
        rag_prefix = ""
        citations: list[str] = []
        if self.campaign_id is not None:
            try:
                from services.rag.context_builder import build_dm_narration_context

                rag_prefix, rag_ctx = build_dm_narration_context(
                    campaign_id=str(self.campaign_id),
                    session_id=str(session_id) if session_id else None,
                    user_context=context or json.dumps(tool_result, default=str)[:300],
                )
                citations = rag_ctx.citations
            except Exception as e:  # never block narration on RAG
                logging.info("DM RAG injection skipped: %s", e)

        prompt_parts = []
        if rag_prefix:
            prompt_parts.append(rag_prefix)
        prompt_parts.append(
            f"""TASK: Narrate the following game event result.

Event Data:
{json.dumps(tool_result, indent=2, default=str)}

Context:
{context}

Provide dramatic, atmospheric narration of what happened. Do NOT change any mechanical results."""
        )
        prompt = "\n\n".join(prompt_parts)

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
        narration = result.get("narration", result.get("error", "The scene unfolds..."))
        if return_citations:
            return {"narration": narration, "citations": citations}
        return narration

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
When NPC KNOWLEDGE CONTEXT is provided, it is everything this NPC plausibly knows.
You MUST NOT reveal information outside that context. Do not invent lore.
Respond in JSON with "dialogue" (what the NPC says) and "action" (brief physical action, optional)."""

    def __init__(self, campaign_id: Optional[uuid.UUID] = None):
        self.campaign_id = campaign_id
        self.llm = LLMAdapter(role="npc", campaign_id=campaign_id)

    def generate_dialogue(
        self,
        npc_name: str,
        npc_sheet: dict,
        emotional_state: str,
        context: str,
        speaker_message: str = "",
        *,
        session_id: Optional[uuid.UUID] = None,
        npc_entity_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Generate NPC dialogue. RAG-filtered for npc_dialogue purpose —
        only public + party visibility chunks reach the prompt, and if
        the NPC has `known_lore_tags` configured in their public_sheet,
        chunks must overlap those tags.

        This is the critical leak boundary: dm_only lore must NEVER
        surface in NPC dialogue regardless of how relevant cosine
        similarity thinks it is. The filter happens in services/rag/
        filters.py:filter_chunk_visibility before the prompt is built."""
        rag_prefix = ""
        if self.campaign_id is not None:
            try:
                from services.rag.context_builder import build_npc_dialogue_context

                rag_prefix, _ = build_npc_dialogue_context(
                    campaign_id=str(self.campaign_id),
                    session_id=str(session_id) if session_id else None,
                    npc_entity_id=str(npc_entity_id) if npc_entity_id else None,
                    player_utterance=speaker_message or context,
                )
            except Exception as e:
                logging.info("NPC RAG injection skipped: %s", e)

        prompt_parts = []
        if rag_prefix:
            prompt_parts.append(rag_prefix)
        prompt_parts.append(
            f"""You are {npc_name}.

Your character sheet: {json.dumps(npc_sheet, default=str)}
Current emotional state: {emotional_state}
Scene context: {context}
"""
        )
        if speaker_message:
            prompt_parts.append(f'\nSomeone says to you: "{speaker_message}"\n')
        prompt_parts.append("\nRespond in character.")

        result = self.llm.generate_structured(
            self.SYSTEM_PROMPT,
            "".join(prompt_parts),
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
