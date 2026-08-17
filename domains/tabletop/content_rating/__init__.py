from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContentDecision:
    allowed: bool
    rating: str
    matched_boundaries: tuple[str, ...]


class ContentPolicy:
    """Deterministic boundary gate; model narration is evaluated after mechanics."""

    def __init__(self, blocked_terms: tuple[str, ...] = ()) -> None:
        self.blocked_terms = tuple(term.casefold() for term in blocked_terms)

    def evaluate(self, text: str, rating: str = "TEEN") -> ContentDecision:
        folded = text.casefold()
        matched = tuple(term for term in self.blocked_terms if term in folded)
        return ContentDecision(not matched, rating, matched)
