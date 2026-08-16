-- 011_map_decorations.sql
-- Visual flavor objects on maps. Distinct from POIs:
--   - POI:        named, interactive, can drill into a child map, has rules-relevant
--                 metadata (treasure / hazard / building / NPC marker)
--   - Decoration: pure flavor, no interaction, no name. Just makes a place look
--                 like a place. Trees on a forest tile, rocks scattered on dirt,
--                 barrels in a corner, torches near walls.
--
-- Rendered as billboard sprites on top of the floor tile, do not block movement.

CREATE TABLE IF NOT EXISTS state.map_decorations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  map_id uuid NOT NULL REFERENCES state.maps(id) ON DELETE CASCADE,
  x int NOT NULL,
  y int NOT NULL,
  kind text NOT NULL CHECK (kind IN (
    'TREE','BUSH','ROCK','CACTUS','FLOWER',         -- outdoor flora/stones
    'BARREL','CRATE','CHEST','TABLE','CHAIR',       -- room furniture
    'TORCH','BRAZIER','BANNER','RUG',               -- ambient
    'FOUNTAIN','WELL','SHRINE',                     -- features
    'GENERIC'
  )),
  -- 0..3 for north/east/south/west facing where it makes sense (banners, chairs)
  facing smallint NOT NULL DEFAULT 0,
  -- Optional uploaded sprite. When NULL, renderer uses a default glyph for kind.
  image_url text NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_map_decorations_map ON state.map_decorations(map_id);
CREATE INDEX IF NOT EXISTS idx_map_decorations_xy ON state.map_decorations(map_id, x, y);
