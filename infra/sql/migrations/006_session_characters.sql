-- Migration 006: Session Characters tracking and entity enhancements
-- Tracks which characters are part of each session and their status

-- Add image_url to entities for character portraits
ALTER TABLE state.entities ADD COLUMN IF NOT EXISTS image_url TEXT;

-- Add status column for soft-delete (tombstone) functionality
ALTER TABLE state.entities ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'TOMBSTONED', 'PURGED'));

CREATE INDEX IF NOT EXISTS idx_entities_status ON state.entities(status);

-- Session characters join table - tracks which entities are in which session
CREATE TABLE IF NOT EXISTS state.session_characters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES state.sessions(id) ON DELETE CASCADE,
    entity_id UUID NOT NULL REFERENCES state.entities(id) ON DELETE CASCADE,

    -- Status within this specific session
    -- ACTIVE: Currently participating
    -- DEAD: Died during this session (can be revived)
    -- REMOVED: Manually removed from session
    -- RETIRED: Character retired/left the party
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DEAD', 'REMOVED', 'RETIRED')),

    -- When character joined/left this session
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    left_at TIMESTAMPTZ,

    -- Death tracking for potential revival
    death_round INT,  -- Combat round when death occurred
    death_details JSONB,  -- How they died, for narration purposes
    revived_at TIMESTAMPTZ,  -- When/if they were revived
    revive_details JSONB,  -- How they were revived

    -- Prevent duplicate entries
    UNIQUE(session_id, entity_id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_session_characters_session ON state.session_characters(session_id);
CREATE INDEX IF NOT EXISTS idx_session_characters_entity ON state.session_characters(entity_id);
CREATE INDEX IF NOT EXISTS idx_session_characters_status ON state.session_characters(session_id, status);

-- Track death history across the campaign (for revival restrictions)
CREATE TABLE IF NOT EXISTS state.entity_death_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES state.entities(id) ON DELETE CASCADE,
    campaign_id UUID NOT NULL REFERENCES state.campaigns(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES state.sessions(id) ON DELETE CASCADE,

    death_type TEXT NOT NULL CHECK (death_type IN ('COMBAT', 'TRAP', 'ENVIRONMENTAL', 'STORY', 'OTHER')),
    death_details JSONB,

    -- Revival tracking
    is_revived BOOLEAN NOT NULL DEFAULT FALSE,
    revived_in_session_id UUID REFERENCES state.sessions(id),
    revive_method TEXT,  -- 'SPELL', 'DIVINE_INTERVENTION', 'STORY', etc.
    revive_details JSONB,

    died_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revived_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_entity_death_history_entity ON state.entity_death_history(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_death_history_campaign ON state.entity_death_history(campaign_id, is_revived);

-- Function to check if an entity can join a session (not permanently dead in campaign)
CREATE OR REPLACE FUNCTION state.can_entity_join_session(
    p_entity_id UUID,
    p_campaign_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    v_unrevived_deaths INT;
BEGIN
    -- Count deaths that haven't been revived
    SELECT COUNT(*) INTO v_unrevived_deaths
    FROM state.entity_death_history
    WHERE entity_id = p_entity_id
      AND campaign_id = p_campaign_id
      AND is_revived = FALSE;

    -- Can join if no unrevived deaths
    RETURN v_unrevived_deaths = 0;
END;
$$ LANGUAGE plpgsql;
