from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel.contracts import EventEnvelopeV2, VerifierFact

Verifier = Callable[[tuple[EventEnvelopeV2, ...], dict[str, Any]], tuple[VerifierFact, ...]]


class VerifierRegistry:
    """Versioned deterministic verifier contracts producing normalized facts only."""

    def __init__(self) -> None:
        self._verifiers: dict[str, Verifier] = {}
        self._latest: dict[str, str] = {}

    def register(self, name: str, verifier: Verifier, *, version: str = "1.0.0") -> str:
        reference = f"{name}@{version}"
        if reference in self._verifiers:
            raise ValueError(f"Verifier already registered: {reference}")
        self._verifiers[reference] = verifier
        self._latest[name] = reference
        return reference

    def verify(
        self,
        names: tuple[str, ...],
        events: tuple[EventEnvelopeV2, ...],
        final_state: dict[str, Any],
    ) -> tuple[VerifierFact, ...]:
        facts: list[VerifierFact] = []
        for requested in names:
            reference = requested if "@" in requested else self._latest.get(requested)
            if reference is None or reference not in self._verifiers:
                raise ValueError(f"Unknown verifier: {requested}")
            emitted = self._verifiers[reference](events, final_state)
            if not all(isinstance(fact, VerifierFact) for fact in emitted):
                raise TypeError(f"Verifier {reference} emitted a non-normalized fact")
            facts.extend(emitted)
        return tuple(facts)
