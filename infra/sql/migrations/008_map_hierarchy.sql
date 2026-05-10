-- 008_map_hierarchy.sql
-- Add World / Area / Room tier hierarchy to state.maps so a campaign can have
-- one world map containing several areas, each containing rooms. The renderer
-- uses kind to pick the right zoom presentation; parent_map_id wires drilldown.
--
-- Encounter-tier tactical maps stay represented as ROOMs that combat overlays
-- on top of, rather than a separate kind, so existing encounter flows are
-- unchanged.

ALTER TABLE state.maps
  ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'ROOM'
    CHECK (kind IN ('WORLD', 'AREA', 'ROOM')),
  ADD COLUMN IF NOT EXISTS parent_map_id uuid NULL
    REFERENCES state.maps(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_maps_campaign_kind ON state.maps(campaign_id, kind);
CREATE INDEX IF NOT EXISTS idx_maps_parent ON state.maps(parent_map_id);

-- Backfill: any pre-existing map keeps kind='ROOM' (the DEFAULT) and no parent.
-- Procedural generation from now on sets kind explicitly.
