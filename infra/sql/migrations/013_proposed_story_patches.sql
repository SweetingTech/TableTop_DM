-- 013_proposed_story_patches.sql
-- Session Intelligence (Phase 33–38).
--
-- The session-intel layer observes chat / ledger events, extracts candidate
-- narrative deltas, and proposes patches to state.story_state and related
-- continuity surfaces. Those proposals queue here instead of mutating state
-- directly — only after a DM approves (or an auto-approval policy fires)
-- does the patcher actually commit.
--
-- This preserves the project's prime directive: LLMs propose; deterministic
-- backend commits. The same "one path to reality" model as /api/propose,
-- now extended from explicit actions to inferred narrative facts.

CREATE TABLE IF NOT EXISTS state.proposed_story_patches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id) ON DELETE CASCADE,
  session_id uuid NOT NULL REFERENCES state.sessions(id) ON DELETE CASCADE,
  -- Where the proposal came from. 'chat' = parsed DIALOGUE events from the
  -- ledger; 'transcript' = audio→text (future); 'ledger_event' = derived
  -- from a STATE_DELTA / TOOL_CALL row; 'dm_note' = DM-typed observation.
  source_kind text NOT NULL CHECK (source_kind IN ('chat', 'transcript', 'ledger_event', 'dm_note')),
  source_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- What kind of narrative fact this proposes. Matches the
  -- StoryEventType enum in shared/schemas/session_intel.py.
  event_type text NOT NULL,
  -- Short human-readable summary the DM sees in the review queue.
  summary text NOT NULL,
  -- Entities the event touches (UUIDs or string names if not yet entity-ified).
  entities jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- The actual state delta to apply on approval. Schema depends on event_type.
  -- See services/session_intel/patcher.py for the dispatch table.
  patch jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Provenance — the LLM extractor must cite WHY it thinks this is true.
  evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
  -- Confidence in [0, 1]. 1.0 means deterministic (e.g. derived from a
  -- STATE_DELTA row). Lower = more uncertain narrative inference.
  confidence numeric(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  -- Visibility scope of the resulting narrative fact, NOT of the proposal
  -- itself. The DM always sees pending proposals.
  visibility text NOT NULL CHECK (visibility IN ('public', 'party', 'dm_only', 'principal_scoped')),
  -- Workflow status.
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EDITED', 'APPLIED', 'SUPERSEDED')),
  -- When the patcher actually commits, link the resulting ledger event so
  -- we can trace back from canonical state to the proposal that produced it.
  applied_event_id uuid NULL REFERENCES ledger.session_ledger(event_id),
  created_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz NULL,
  reviewed_by uuid NULL REFERENCES state.principals(id) ON DELETE SET NULL,
  notes text NULL
);

CREATE INDEX IF NOT EXISTS idx_patches_session ON state.proposed_story_patches(session_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_patches_campaign ON state.proposed_story_patches(campaign_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_patches_event_type ON state.proposed_story_patches(event_type);
