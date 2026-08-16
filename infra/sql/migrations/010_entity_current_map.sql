-- 010_entity_current_map.sql
-- Each entity tracks which map it's currently on. This is the foundation for
-- party decoherence: events get pushed to a player's client only if their
-- PC's current_map_id matches the event's map AND distance is within their
-- perception radius. Phase 6f.
--
-- Backfill: every existing entity is placed on the deepest (ROOM) map of
-- their campaign, since that's where Phase 1-5 testing put them.

ALTER TABLE state.entities
  ADD COLUMN IF NOT EXISTS current_map_id uuid NULL
    REFERENCES state.maps(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_entities_current_map ON state.entities(current_map_id);

-- Backfill existing entities to the campaign's ROOM map (deepest tier).
UPDATE state.entities e
SET current_map_id = (
  SELECT m.id FROM state.maps m
  WHERE m.campaign_id = e.campaign_id AND m.kind = 'ROOM'
  ORDER BY m.created_at DESC LIMIT 1
)
WHERE e.current_map_id IS NULL;
