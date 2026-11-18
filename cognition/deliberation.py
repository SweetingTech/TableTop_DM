from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class DeliberationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    identity_summary: str
    situation: dict[str, Any]
    allowed_actions: tuple[str, ...] = Field(min_length=1)
    seed: int
    prompt_contract_version: str = "deliberation-prompt-1.0.0"

    @field_validator("allowed_actions")
    @classmethod
    def actions_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_actions must be unique")
        return value


class DeliberationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str
    rationale: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)


class ModelUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


@dataclass(frozen=True)
class ProviderCompletion:
    """Transport metadata kept separate from the model's untrusted JSON."""

    content: object = None
    attempts: int = 0
    usage: ModelUsage | None = None
    failure_code: str | None = None


class DeliberationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    response: DeliberationResponse
    used_model: bool
    model_version: str | None = None
    fallback_reason: str | None = None
    provider_attempts: int = Field(default=0, ge=0)
    usage: ModelUsage | None = None


class DeliberationProvider(Protocol):
    @property
    def model_version(self) -> str: ...

    def complete(
        self, request: DeliberationRequest
    ) -> DeliberationResponse | dict[str, Any] | str | ProviderCompletion: ...


class TypedDeliberationGateway:
    """Validates model proposals and deterministically falls back to scored actions."""

    VERSION = "deliberation-gateway-1.0.0"

    def decide(
        self,
        request: DeliberationRequest,
        fallback_scores: dict[str, float],
        provider: DeliberationProvider | None = None,
    ) -> DeliberationResult:
        missing = set(request.allowed_actions) - set(fallback_scores)
        if missing:
            raise ValueError(f"Missing fallback scores for actions: {sorted(missing)}")

        if provider is None:
            return self._fallback(request, fallback_scores, "model_provider_unavailable")

        try:
            raw = provider.complete(request)
        except Exception:  # noqa: BLE001 - contain provider boundary failures
            return self._fallback(
                request,
                fallback_scores,
                "model_provider_error",
                model_version=provider.model_version,
                completion=ProviderCompletion(attempts=1),
            )
        completion = raw if isinstance(raw, ProviderCompletion) else ProviderCompletion(raw, 1)
        reason = completion.failure_code
        if reason is None:
            try:
                content = completion.content
                if isinstance(content, str):
                    content = json.loads(content)
                response = DeliberationResponse.model_validate(content)
            except (ValidationError, ValueError, TypeError):
                reason = "invalid_model_response"
            else:
                if response.action in request.allowed_actions:
                    return DeliberationResult(
                        response=response.model_copy(
                            update={"rationale": "Configured model selected an eligible action."}
                        ),
                        used_model=True,
                        model_version=provider.model_version,
                        provider_attempts=completion.attempts,
                        usage=completion.usage,
                    )
                reason = "model_selected_disallowed_action"
        return self._fallback(
            request,
            fallback_scores,
            reason,
            model_version=provider.model_version,
            completion=completion,
        )

    @staticmethod
    def _fallback(
        request: DeliberationRequest,
        fallback_scores: dict[str, float],
        reason: str,
        *,
        model_version: str | None = None,
        completion: ProviderCompletion | None = None,
    ) -> DeliberationResult:
        action = min(
            request.allowed_actions,
            key=lambda candidate: (-fallback_scores[candidate], candidate),
        )
        return DeliberationResult(
            response=DeliberationResponse(
                action=action,
                rationale=f"Deterministic policy fallback ({reason}).",
                confidence=0.5,
            ),
            used_model=False,
            model_version=model_version,
            fallback_reason=reason,
            provider_attempts=completion.attempts if completion else 0,
            usage=completion.usage if completion else None,
        )
