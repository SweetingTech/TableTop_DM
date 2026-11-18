"""Real utterances from a replaceable provider, without granting it world mutation."""

from __future__ import annotations

import re
import uuid
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from cognition.choice_state import SpeechCadence, speech_cadence, speech_intent
from cognition.context import CharacterContext, experience_summary
from cognition.knowledge import search_known_lore
from kernel.state import stable_hash

PROMPT_VERSION = "character-dialogue-1.3.0"
_META = re.compile(
    r"\b(simulation|simulated|npc|ai|prompt|controller|stand-in|player|"
    r"timeline|rewind|language model|software|developer|system prompt|"
    r"fictional|non-player|scripted|respawn|computer program)\b",
    re.I,
)
_UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)


class DialogueRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: dict
    traits: dict
    intent: str
    volume: str
    language: str = "common"
    cadence: SpeechCadence | None = Field(default=None, exclude_if=lambda v: v is None)
    reply_to: str | None = None
    experiences: tuple[dict[str, str], ...]
    nearby: tuple[dict, ...]
    seed: int


class DialogueAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str = Field(min_length=1, max_length=800)
    sources: tuple[str, ...] = Field(min_length=1, max_length=12)


class DialogueProvider(Protocol):
    @property
    def model_version(self) -> str: ...

    def complete(self, request: DialogueRequest) -> object: ...


class DialogueReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: str = PROMPT_VERSION
    status: Literal["GENERATED", "FALLBACK"]
    reason: str | None = None
    model_version: str
    runtime_kind: Literal["LOCAL_LLM", "HOSTED_LLM"] = "HOSTED_LLM"
    source_event_ids: tuple[uuid.UUID, ...] = ()
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def fiction(text: str) -> str:
    return "" if _META.search(text) or _UUID.search(text) else text[:800]


def generate_dialogue(
    context: CharacterContext,
    parameters: dict,
    traits: dict,
    seed: int,
    provider: DialogueProvider,
    *,
    reply_event_id: uuid.UUID | None = None,
    cadence: SpeechCadence | None = None,
) -> tuple[str, DialogueReceipt]:
    fallback = parameters["text"]
    experiences: list[dict[str, str]] = []
    sources = {}
    own_lines = set()
    incoming_reference = None
    observations = context.observations[-12:]
    if reply_event_id is not None and all(
        item.source_event_id != reply_event_id for item in observations
    ):
        scheduled = next(
            (item for item in context.observations if item.source_event_id == reply_event_id), None
        )
        if scheduled is not None:
            observations = (scheduled, *observations[-11:])
    query = next(
        (
            str(item.perceived_payload["text"])
            for item in reversed(context.observations)
            if isinstance(item.perceived_payload.get("text"), str)
            and (reply_event_id is None or item.source_event_id == reply_event_id)
            and str(item.perceived_payload.get("speaker_entity_id"))
            != str(context.scene.observer_entity_id)
        ),
        "",
    )[:400]
    for item in search_known_lore(context.known_lore, query, limit=8):
        text = fiction(item.text)
        if text:
            reference = "k" + str(len(experiences))
            experiences.append({"reference": reference, "text": text, "speaker": "recollection"})
            sources[reference] = item.source_event_id
    for memory in context.memories[-8:]:
        text = fiction(memory.summary)
        if text:
            reference = "m" + str(len(experiences))
            experiences.append({"reference": reference, "text": text, "speaker": "recollection"})
            sources[reference] = memory.source_event_id
    for observation in observations:
        text = fiction(experience_summary(observation))
        if not text:
            continue
        reference = "e" + str(len(experiences))
        own = str(observation.perceived_payload.get("speaker_entity_id")) == str(
            context.scene.observer_entity_id
        )
        experiences.append(
            {"reference": reference, "text": text, "speaker": "self" if own else "other"}
        )
        sources[reference] = observation.source_event_id
        if own:
            own_lines.add(text.casefold().strip())
        elif observation.perceived_payload.get("speaker_entity_id") and (
            reply_event_id is None or observation.source_event_id == reply_event_id
        ):
            incoming_reference = reference
    identity = context.identity
    authored = identity.authored_identity if identity else None
    request = DialogueRequest(
        identity={
            "name": fiction(identity.name) if identity else "",
            "backstory": fiction(authored.backstory) if authored else "",
            "motives": [fiction(value) for value in authored.motives] if authored else [],
            "values": [fiction(value) for value in authored.values] if authored else [],
        },
        traits={
            key: value
            for key, value in traits.items()
            if key
            in {"communication_directness", "extraversion", "conflict_style", "risk_tolerance"}
        },
        intent=speech_intent(fallback),
        volume=parameters.get("volume", "NORMAL"),
        language=parameters.get("language", "common"),
        cadence=cadence,
        reply_to=incoming_reference,
        experiences=tuple(experiences),
        nearby=tuple(
            {
                "name": fiction(row.name or "someone"),
                "wounded": (
                    row.health < row.max_health / 2
                    if row.health is not None and row.max_health
                    else None
                ),
            }
            for row in context.scene.perceived_entities
            if row.entity_id != context.scene.observer_entity_id
        ),
        seed=seed,
    )
    reason = "no_grounded_experience"
    if experiences and (reply_event_id is None or incoming_reference is not None):
        try:
            answer = DialogueAnswer.model_validate(provider.complete(request))
            if any(reference not in sources for reference in answer.sources) or (
                incoming_reference is not None and incoming_reference not in answer.sources
            ):
                raise ValueError("unknown grounding reference")
            text = answer.text.strip()
            if (
                not text
                or not fiction(text)
                or text.casefold() in own_lines
                or any(marker in text for marker in ("\n", "```", "<script", "*"))
                or (cadence is not None and speech_cadence(text) != cadence)
            ):
                raise ValueError("invalid utterance")
            return text, DialogueReceipt(
                status="GENERATED",
                model_version=provider.model_version,
                runtime_kind=getattr(provider, "runtime_kind", "HOSTED_LLM"),
                source_event_ids=tuple(
                    source
                    for key in dict.fromkeys(answer.sources)
                    if (source := sources[key]) is not None
                ),
                output_hash=stable_hash(text),
            )
        except Exception:  # Contain untrusted provider failure; never log its text or credentials.
            reason = "provider_response_unavailable_or_invalid"
    return fallback, DialogueReceipt(
        status="FALLBACK",
        reason=reason,
        model_version=provider.model_version,
        runtime_kind=getattr(provider, "runtime_kind", "HOSTED_LLM"),
        output_hash=stable_hash(fallback),
    )
