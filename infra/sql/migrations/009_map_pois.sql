-- 009_map_pois.sql
-- Points of interest on a map. Anything spatial that the player can find:
-- buildings, NPCs, signs, hazards, treasure markers, encounter triggers.
--
-- Discovery is class-modulated and runs server-side via the /discovered_pois
-- endpoint (Phase 4). Hidden until your perception radius reaches the tile.

CREATE TABLE IF NOT EXISTS state.map_pois (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  map_id uuid NOT NULL REFERENCES state.maps(id) ON DELETE CASCADE,
  x int NOT NULL,
  y int NOT NULL,
  kind text NOT NULL CHECK (kind IN ('NPC','BUILDING','SIGN','HAZARD','TREASURE','PORTAL','GENERIC')),
  name text NOT NULL,
  description text NULL,
  image_url text NULL,
  -- Optional drilldown target: clicking a BUILDING/PORTAL on the parent map
  -- enters the child map referenced here.
  target_map_id uuid NULL REFERENCES state.maps(id) ON DELETE SET NULL,
  -- Hidden POIs require either GM reveal or proximity discovery.
  is_hidden boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_map_pois_map ON state.map_pois(map_id);
CREATE INDEX IF NOT EXISTS idx_map_pois_xy ON state.map_pois(map_id, x, y);
