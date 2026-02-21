import re
from typing import Optional
from shared.schemas.enums import ContentRating
from shared.schemas.events import EventEnvelope


HARD_BLOCKED_PATTERNS = [
    r'\bminor[s]?\b.*\bsexual\b',
    r'\bchild\b.*\bsexual\b',
    r'\bunder.?age\b.*\bsexual\b',
    r'\bnon.?consensual\s+sexual\b',
]

MATURE_PATTERNS = [
    r'\bgore\b',
    r'\btorture\b',
    r'\bgruesome\b',
    r'\bexplicit\s+violence\b',
]

EXPLICIT_PATTERNS = [
    r'\bsexual\b',
    r'\bnudity\b',
    r'\berotic\b',
]


class ContentRatingGate:

    def __init__(self, campaign_rating: ContentRating = ContentRating.SAFE):
        self.campaign_rating = campaign_rating

    def check_content(self, text: str) -> dict:
        text_lower = text.lower()

        for pattern in HARD_BLOCKED_PATTERNS:
            if re.search(pattern, text_lower):
                return {
                    "allowed": False,
                    "reason": "Content violates hard block rules",
                    "blocked": True,
                    "category": "HARD_BLOCK",
                }

        if self.campaign_rating == ContentRating.SAFE:
            for pattern in MATURE_PATTERNS:
                if re.search(pattern, text_lower):
                    return {
                        "allowed": False,
                        "reason": "Content exceeds SAFE rating",
                        "blocked": True,
                        "category": "MATURE_IN_SAFE",
                    }
            for pattern in EXPLICIT_PATTERNS:
                if re.search(pattern, text_lower):
                    return {
                        "allowed": False,
                        "reason": "Content exceeds SAFE rating",
                        "blocked": True,
                        "category": "EXPLICIT_IN_SAFE",
                    }

        elif self.campaign_rating == ContentRating.MATURE:
            for pattern in EXPLICIT_PATTERNS:
                if re.search(pattern, text_lower):
                    return {
                        "allowed": False,
                        "reason": "Content exceeds MATURE rating (fade-to-black)",
                        "blocked": True,
                        "category": "EXPLICIT_IN_MATURE",
                    }

        return {"allowed": True, "blocked": False}

    def filter_event(self, event: EventEnvelope) -> Optional[EventEnvelope]:
        payload = event.payload or {}
        texts_to_check = []

        for key in ("narration", "dialogue", "message", "description"):
            if key in payload and isinstance(payload[key], str):
                texts_to_check.append(payload[key])

        for text in texts_to_check:
            result = self.check_content(text)
            if not result["allowed"]:
                return None

        return event

    def filter_llm_output(self, output: str) -> dict:
        result = self.check_content(output)
        if not result["allowed"]:
            return {
                "filtered": True,
                "original_blocked": True,
                "replacement": "[Content filtered due to rating restrictions]",
                "reason": result["reason"],
            }
        return {"filtered": False, "text": output}
