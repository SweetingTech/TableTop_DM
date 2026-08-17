from __future__ import annotations

import json
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


class DeliberationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    response: DeliberationResponse
    used_model: bool
    model_version: str | None = None
    fallback_reason: str | None = None


class DeliberationProvider(Protocol):
    model_version: str

    def complete(
        self, request: DeliberationRequest
    ) -> DeliberationResponse | dict[str, Any] | str: ...


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

        if provider is not None:
            try:
                raw = provider.complete(request)
                if isinstance(raw, str):
                    raw = json.loads(raw)
                response = (
                    raw
                    if isinstance(raw, DeliberationResponse)
                    else DeliberationResponse.model_validate(raw)
                )
                if response.action not in request.allowed_actions:
                    return self._fallback(
                        request,
                        fallback_scores,
                        f"model_selected_disallowed_action:{response.action}",
                    )
                return DeliberationResult(
                    response=response,
                    used_model=True,
                    model_version=provider.model_version,
                )
            except (
                ValidationError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                return self._fallback(
                    request,
                    fallback_scores,
                    f"invalid_model_response:{type(exc).__name__}",
                )
            except Exception as exc:  # noqa: BLE001 - contain provider boundary failures
                return self._fallback(
                    request,
                    fallback_scores,
                    f"model_provider_error:{type(exc).__name__}",
                )

        return self._fallback(request, fallback_scores, "model_provider_unavailable")

    @staticmethod
    def _fallback(
        request: DeliberationRequest,
        fallback_scores: dict[str, float],
        reason: str,
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
            fallback_reason=reason,
        )
