"""Contracts for session-intelligence extraction (Phase 35).

The extractor is an LLM call that must return ExtractedStoryEvent[] —
nothing more, nothing less. Free-form prose is rejected. Everything is
schema-validated before it can become a proposed_story_patches row.

This mirrors the project's prime directive: LLMs propose schema-validated
deltas, deterministic backend commits.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# Visibility for the narrative fact this event represents. The proposal
# itself is always DM-visible — that's the whole point of a review queue.
Visibility = Literal["public", "party", "dm_only", "principal_scoped"]


# Categories of narrative event the extractor can emit. Kept small and
# explicit so the LLM has no excuse to invent fields. New types require
# a code change here, a patcher dispatch entry, and a UI label.
StoryEventType = Literal[
    "scene_started",
    "scene_ended",
    "location_changed",
    "npc_introduced",
    "npc_updated",
    "npc_attitude_changed",
    "quest_introduced",
    "quest_updated",
    "secret_revealed",
    "promise_made",
    "threat_created",
    "consequence_created",
    "loot_gained",
    "item_used",
    "unresolved_thread",
    "retcon_or_contradiction",
]


SourceKind = Literal["chat", "transcript", "ledger_event", "dm_note"]


class Evidence(BaseModel):
    """Provenance the extractor must attach to every proposal.

    Without evidence, a "fact" is just an LLM hallucination wearing a
    confidence score as a hat. We require it so the DM can audit each
    item in the review queue before approving.
    """
    source_kind: SourceKind
    source_id: str = Field(..., description="ledger seq_id, chat message id, or transcript chunk id")
    quote: Optional[str] = Field(None, description="verbatim text the inference rests on")
    timestamp_start: Optional[str] = None
    timestamp_end: Optional[str] = None


class ExtractedStoryEvent(BaseModel):
    """One candidate narrative delta proposed by the extractor.

    The `proposed_state_delta` payload's shape depends on `event_type`.
    See services/session_intel/patcher.py for the per-type dispatcher;
    that's where the canonical "this delta applies to that story_state
    field" mapping lives.
    """
    event_type: StoryEventType
    summary: str = Field(..., max_length=400, description="one-line description for the review queue")
    entities: list[str] = Field(default_factory=list, description="entity UUIDs or pre-canonical names")
    proposed_state_delta: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    visibility: Visibility = "party"
    requires_dm_review: bool = True


class ExtractionRequest(BaseModel):
    """Input shape for the extractor service."""
    campaign_id: str
    session_id: str
    # Limit how far back to look. Default behavior is "since last extraction".
    since_seq_id: Optional[int] = None
    until_seq_id: Optional[int] = None
    # Skip the LLM and just produce events from ledger STATE_DELTA rows.
    # Useful for offline mode and unit tests.
    deterministic_only: bool = False


class ExtractionResult(BaseModel):
    """Output of the extractor — what we wrote into the review queue."""
    proposed_count: int
    patch_ids: list[str]
    skipped: list[str] = Field(
        default_factory=list,
        description="reasons we couldn't / didn't extract certain ledger rows",
    )


class DMReviewPacket(BaseModel):
    """The 'after every session' deliverable.

    Aggregated view of everything the session-intel layer thinks needs DM
    attention. The DM can approve/reject/edit each patch from a single
    surface instead of clicking through ten tabs.
    """
    session_id: str
    campaign_id: str
    generated_at: str
    pending_patches: list[dict]
    party_recap: str
    dm_recap: str
    open_threads: list[dict] = Field(default_factory=list)
    unresolved_promises: list[dict] = Field(default_factory=list)
    contradictions: list[dict] = Field(default_factory=list)
