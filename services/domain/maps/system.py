import uuid
import json
from shared.db.connection import execute_query, execute_one, get_connection
from shared.schemas.events import StateDelta


class MapSystem:
    def create_map(
        self,
        campaign_id: uuid.UUID,
        name: str,
        width: int,
        height: int,
        grid_size: int = 5,
        kind: str = "ROOM",
        parent_map_id: uuid.UUID = None,
        conn=None,
    ) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            map_id = uuid.uuid4()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO state.maps
                  (id, campaign_id, name, width, height, grid_size, kind, parent_map_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    str(map_id),
                    str(campaign_id),
                    name,
                    width,
                    height,
                    grid_size,
                    kind,
                    str(parent_map_id) if parent_map_id else None,
                ),
            )

            if own_conn:
                conn.commit()
            cur.close()
            return {"map_id": str(map_id), "name": name, "kind": kind}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def set_map_node(
        self,
        map_id: uuid.UUID,
        tier: int,
        x: int,
        y: int,
        collision_mask: str = "0" * 16,
        terrain: dict = None,
        conn=None,
    ) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            node_id = uuid.uuid4()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO state.map_nodes (id, map_id, tier, x, y, collision_mask, terrain)
                VALUES (%s, %s, %s, %s, %s, %s::bit(16), %s)
                ON CONFLICT (map_id, tier, x, y) DO UPDATE SET
                    collision_mask = EXCLUDED.collision_mask,
                    terrain = EXCLUDED.terrain
            """,
                (
                    str(node_id),
                    str(map_id),
                    tier,
                    x,
                    y,
                    collision_mask,
                    json.dumps(terrain or {}),
                ),
            )

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "node_id": str(node_id)}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def get_map_data(self, map_id: uuid.UUID) -> dict:
        map_row = execute_one("SELECT * FROM state.maps WHERE id = %s", (str(map_id),))
        if not map_row:
            return {"error": "Map not found"}

        nodes = execute_query(
            "SELECT * FROM state.map_nodes WHERE map_id = %s ORDER BY tier, y, x",
            (str(map_id),),
        )

        return {
            "map": dict(map_row),
            "nodes": [dict(n) for n in nodes],
        }

    def apply_destruction(
        self, map_id: uuid.UUID, x: int, y: int, tier: int = 0, conn=None
    ) -> StateDelta:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE state.map_nodes
                SET terrain = jsonb_set(terrain, '{destroyed}', 'true'::jsonb),
                    collision_mask = B'1111111111111111'
                WHERE map_id = %s AND tier = %s AND x = %s AND y = %s
            """,
                (str(map_id), tier, x, y),
            )

            if own_conn:
                conn.commit()
            cur.close()

            return StateDelta(
                table="state.map_nodes",
                operation="UPDATE",
                changes={"map_id": str(map_id), "x": x, "y": y, "destroyed": True},
                domain_tags=["destruction", "map_change"],
            )
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()


class ProceduralMapGenerator:
    """Themed scene generation per tier (Phase 7).

    Each tier has its own composer that produces tiles consistent with what
    a tile of that kind *should* be:

      - ROOM   → walled enclosure with one or two doorways, mostly stone
                 floor, optional rubble cluster + water feature.
      - AREA   → biome-dominant zone (forest / plains / desert / coastal /
                 town) with one terrain class dominant + a winding path.
      - WORLD  → Voronoi-style regional biomes; a few mountain wall tiles.

    The composers return a flat list of {x, y, terrain, is_wall, difficult}
    dicts. ``generate_map`` writes those to ``state.map_nodes``.
    """
    TERRAIN_TYPES = ["stone_floor", "grass", "dirt", "water", "sand", "wood"]

    # Biome → (dominant terrain, secondary terrain, path terrain, is_arid)
    BIOMES = {
        "forest":  ("grass", "dirt",        "dirt",        False),
        "plains":  ("grass", "dirt",        "dirt",        False),
        "desert":  ("sand",  "dirt",        "dirt",        True),
        "coastal": ("sand",  "water",       "sand",        False),
        "tundra":  ("dirt",  "stone_floor", "stone_floor", False),
        "town":    ("stone_floor", "wood",  "stone_floor", False),
    }

    def generate_map(
        self,
        campaign_id: uuid.UUID,
        name: str,
        width: int,
        height: int,
        seed: int = 42,
        grid_size: int = 5,
        kind: str = "ROOM",
        parent_map_id: uuid.UUID = None,
        biome: str = None,
    ) -> dict:
        import random

        rng = random.Random(seed)
        if kind == "ROOM":
            tiles, decorations = self._compose_room(width, height, rng)
        elif kind == "AREA":
            tiles, decorations = self._compose_area(width, height, rng, biome=biome)
        elif kind == "WORLD":
            tiles, decorations = self._compose_world(width, height, rng)
        else:
            tiles, decorations = self._compose_room(width, height, rng)

        map_system = MapSystem()
        result = map_system.create_map(
            campaign_id, name, width, height, grid_size, kind, parent_map_id
        )
        map_id = uuid.UUID(result["map_id"])

        conn = get_connection()
        try:
            cur = conn.cursor()
            for t in tiles:
                walkable = not t["is_wall"]
                collision = "0" * 16 if walkable else "1" + "0" * 15
                terrain_type = "wall" if t["is_wall"] else t["terrain"]
                map_system.set_map_node(
                    map_id, 0, t["x"], t["y"], collision,
                    {"type": terrain_type, "difficult": t["difficult"]},
                    conn,
                )
            for d in decorations:
                cur.execute(
                    """
                    INSERT INTO state.map_decorations (map_id, x, y, kind, facing, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (str(map_id), d["x"], d["y"], d["kind"], d.get("facing", 0),
                     json.dumps(d.get("metadata") or {})),
                )
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        return {
            "map_id": str(map_id),
            "name": name,
            "width": width,
            "height": height,
            "seed": seed,
            "kind": kind,
            "parent_map_id": str(parent_map_id) if parent_map_id else None,
            "decorations": len(decorations),
        }

    # ---------- composers ----------

    def _compose_room(self, w: int, h: int, rng):
        """A walled tactical room: outer wall ring with 1-2 doorway gaps,
        mostly stone floor with the occasional wood/rubble feature.

        Returns (tiles, decorations).
        """
        # 1. Carve doorways before laying down the wall ring.
        door_count = rng.choice([1, 1, 2])
        sides = ["n", "s", "e", "w"]
        rng.shuffle(sides)
        doorways = set()
        for side in sides[:door_count]:
            if side == "n":
                doorways.add((rng.randint(2, w - 3), 0))
            elif side == "s":
                doorways.add((rng.randint(2, w - 3), h - 1))
            elif side == "w":
                doorways.add((0, rng.randint(2, h - 3)))
            else:
                doorways.add((w - 1, rng.randint(2, h - 3)))

        # 2. Wall ring minus doorway tiles.
        walls = set()
        for x in range(w):
            walls.add((x, 0)); walls.add((x, h - 1))
        for y in range(h):
            walls.add((0, y)); walls.add((w - 1, y))
        walls -= doorways

        # 3. Optional interior pillars (0-3).
        for _ in range(rng.randint(0, 3)):
            walls.add((rng.randint(2, w - 3), rng.randint(2, h - 3)))

        # 4. Maybe a rubble cluster of difficult terrain (3-7 tiles).
        rubble = set()
        if rng.random() < 0.65:
            cx, cy = rng.randint(3, w - 4), rng.randint(3, h - 4)
            for _ in range(rng.randint(3, 7)):
                rx = max(1, min(w - 2, cx + rng.randint(-2, 2)))
                ry = max(1, min(h - 2, cy + rng.randint(-2, 2)))
                rubble.add((rx, ry))

        # 5. Maybe a water tile or two (basin/well).
        water = set()
        if rng.random() < 0.4:
            wx, wy = rng.randint(2, w - 3), rng.randint(2, h - 3)
            water.add((wx, wy))
            if rng.random() < 0.5:
                water.add((wx + rng.choice([-1, 1]), wy))

        # 6. Maybe a wood-plank platform — a coherent rectangular patch instead
        # of scattered wood tiles. ~50% of rooms get one.
        wood_patch = set()
        if rng.random() < 0.5:
            pw, ph = rng.randint(2, 4), rng.randint(2, 3)
            px = rng.randint(2, w - 2 - pw)
            py = rng.randint(2, h - 2 - ph)
            for dx in range(pw):
                for dy in range(ph):
                    wood_patch.add((px + dx, py + dy))

        # 7. Lay tiles.
        out = []
        floor_tiles = []  # walkable, non-water — eligible for decorations
        for y in range(h):
            for x in range(w):
                if (x, y) in walls:
                    out.append({"x": x, "y": y, "terrain": "wall", "is_wall": True, "difficult": False})
                elif (x, y) in water:
                    out.append({"x": x, "y": y, "terrain": "water", "is_wall": False, "difficult": False})
                elif (x, y) in rubble:
                    t = rng.choice(["stone_floor", "dirt"])
                    out.append({"x": x, "y": y, "terrain": t, "is_wall": False, "difficult": True})
                    floor_tiles.append((x, y))
                elif (x, y) in wood_patch:
                    out.append({"x": x, "y": y, "terrain": "wood", "is_wall": False, "difficult": False})
                    floor_tiles.append((x, y))
                else:
                    out.append({"x": x, "y": y, "terrain": "stone_floor", "is_wall": False, "difficult": False})
                    floor_tiles.append((x, y))

        # 7. Decorations: barrels/crates near walls, a chest, torches by walls,
        # maybe a table. Pick distinct floor tiles so we don't double up.
        decorations = []
        used = set()
        def pick_unused():
            tries = 0
            while tries < 30:
                tries += 1
                cand = rng.choice(floor_tiles) if floor_tiles else None
                if cand and cand not in used:
                    used.add(cand)
                    return cand
            return None
        # Helper: is a tile adjacent to a wall? Torches go there.
        wall_adj = {(x, y) for (x, y) in floor_tiles
                    if any((x + dx, y + dy) in walls for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)))}
        wall_adj_list = list(wall_adj)
        rng.shuffle(wall_adj_list)
        for (tx, ty) in wall_adj_list[:rng.randint(1, 3)]:
            if (tx, ty) in used:
                continue
            used.add((tx, ty))
            decorations.append({"x": tx, "y": ty, "kind": "TORCH"})
        for _ in range(rng.randint(1, 3)):
            spot = pick_unused()
            if spot:
                decorations.append({"x": spot[0], "y": spot[1], "kind": rng.choice(["BARREL","CRATE"])})
        if rng.random() < 0.7:
            spot = pick_unused()
            if spot:
                decorations.append({"x": spot[0], "y": spot[1], "kind": "CHEST"})
        if rng.random() < 0.4:
            spot = pick_unused()
            if spot:
                decorations.append({"x": spot[0], "y": spot[1], "kind": "TABLE"})
                # chair next to the table if there's room
                for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                    nb = (spot[0]+dx, spot[1]+dy)
                    if nb in floor_tiles and nb not in used:
                        used.add(nb)
                        decorations.append({"x": nb[0], "y": nb[1], "kind": "CHAIR"})
                        break
        return out, decorations

    def _compose_area(self, w: int, h: int, rng, biome: str = None):
        """Outdoor zone: pick a biome, fill with its dominant terrain, drop in
        a meandering path of secondary terrain, and scatter a feature cluster.
        No outer walls — areas are open.

        Returns (tiles, decorations).
        """
        biome = biome or rng.choice(list(self.BIOMES.keys()))
        dom, secondary, path_terrain, _arid = self.BIOMES[biome]

        # 1. Random-walk path from one edge to another. This gives a believable
        #    travel route through the zone instead of speckled noise.
        path = set()
        edge = rng.choice(["n", "s", "e", "w"])
        if edge in ("n", "s"):
            x = rng.randint(2, w - 3)
            y = 0 if edge == "n" else h - 1
        else:
            x = 0 if edge == "w" else w - 1
            y = rng.randint(2, h - 3)
        steps = w + h
        for _ in range(steps):
            path.add((x, y))
            # widen path occasionally
            if rng.random() < 0.3:
                path.add((max(0, min(w - 1, x + rng.choice([-1, 1]))), y))
            # bias toward opposite edge
            dx = rng.choice([-1, 0, 0, 1, 1]) if edge == "w" else \
                 rng.choice([-1, -1, 0, 0, 1]) if edge == "e" else \
                 rng.choice([-1, 0, 0, 1])
            dy = rng.choice([0, 0, 1]) if edge == "n" else \
                 rng.choice([-1, 0, 0]) if edge == "s" else \
                 rng.choice([-1, 0, 0, 1])
            x = max(0, min(w - 1, x + dx))
            y = max(0, min(h - 1, y + dy))

        # 2. Feature cluster — coastal gets a water bay, forest gets dense
        #    "thicket" of difficult tiles, etc.
        cluster = set()
        cx, cy = rng.randint(3, w - 4), rng.randint(3, h - 4)
        cluster_terrain = secondary
        cluster_difficult = biome == "forest"
        for _ in range(rng.randint(8, 20)):
            ax = max(0, min(w - 1, cx + rng.randint(-3, 3)))
            ay = max(0, min(h - 1, cy + rng.randint(-3, 3)))
            cluster.add((ax, ay))

        # 3. Sparse obstacle "rocks" — impassable wall tiles, but only 2-5.
        rocks = set()
        for _ in range(rng.randint(2, 5)):
            rx, ry = rng.randint(1, w - 2), rng.randint(1, h - 2)
            if (rx, ry) not in path:
                rocks.add((rx, ry))

        out = []
        floor_tiles = []
        for y in range(h):
            for x in range(w):
                if (x, y) in rocks:
                    out.append({"x": x, "y": y, "terrain": "wall", "is_wall": True, "difficult": False})
                elif (x, y) in path:
                    out.append({"x": x, "y": y, "terrain": path_terrain, "is_wall": False, "difficult": False})
                    floor_tiles.append((x, y, "path"))
                elif (x, y) in cluster:
                    out.append({"x": x, "y": y, "terrain": cluster_terrain, "is_wall": False, "difficult": cluster_difficult})
                    floor_tiles.append((x, y, "cluster"))
                else:
                    t = secondary if rng.random() < 0.08 else dom
                    out.append({"x": x, "y": y, "terrain": t, "is_wall": False, "difficult": False})
                    floor_tiles.append((x, y, "dom"))

        # Decorations vary by biome.
        flora_kinds = {
            "forest":  ["TREE","TREE","TREE","BUSH","FLOWER"],
            "plains":  ["BUSH","FLOWER","FLOWER","ROCK","TREE"],
            "desert":  ["CACTUS","CACTUS","ROCK","ROCK"],
            "coastal": ["ROCK","BUSH","FLOWER"],
            "tundra":  ["ROCK","ROCK","BUSH"],
            "town":    ["BARREL","CRATE","BANNER","TABLE"],
        }
        kinds = flora_kinds.get(biome, ["ROCK","BUSH"])
        decorations = []
        used = set()
        # density: forest dense, desert sparse, town moderate
        density = {"forest": 0.10, "plains": 0.05, "desert": 0.04,
                   "coastal": 0.05, "tundra": 0.04, "town": 0.07}.get(biome, 0.06)
        target = int(w * h * density)
        # Don't decorate path tiles (it should look traversable).
        candidates = [(x, y) for (x, y, kind) in floor_tiles if kind != "path"]
        rng.shuffle(candidates)
        for (cx, cy) in candidates[:target]:
            if (cx, cy) in used:
                continue
            used.add((cx, cy))
            decorations.append({"x": cx, "y": cy, "kind": rng.choice(kinds)})
        return out, decorations

    def _compose_world(self, w: int, h: int, rng):
        """Overworld view: ~6 Voronoi-style biome regions, with a mountain
        ridge and possibly a coastline/lake. World tiles are walkable except
        for sparse mountain walls; combat doesn't happen here.

        Returns (tiles, decorations).
        """
        # 1. Pick 5-7 region seeds, assign each a biome.
        seed_count = rng.randint(5, 7)
        seeds = []
        for _ in range(seed_count):
            seeds.append((
                rng.randint(0, w - 1),
                rng.randint(0, h - 1),
                rng.choice(list(self.BIOMES.keys())),
            ))

        # 2. Mountain ridge — a Bresenham-ish line of wall tiles.
        ridge = set()
        if rng.random() < 0.7:
            x0, y0 = rng.randint(0, w - 1), rng.randint(0, h - 1)
            x1, y1 = rng.randint(0, w - 1), rng.randint(0, h - 1)
            steps = max(abs(x1 - x0), abs(y1 - y0))
            for i in range(steps + 1):
                t = i / max(1, steps)
                rx = round(x0 + (x1 - x0) * t)
                ry = round(y0 + (y1 - y0) * t)
                if 0 <= rx < w and 0 <= ry < h:
                    ridge.add((rx, ry))
                    # mountains are thick — add neighbors with low chance
                    if rng.random() < 0.35:
                        ridge.add((min(w - 1, rx + 1), ry))

        out = []
        tile_biome = {}  # (x,y) -> biome name, for decoration placement
        for y in range(h):
            for x in range(w):
                if (x, y) in ridge:
                    out.append({"x": x, "y": y, "terrain": "wall", "is_wall": True, "difficult": False})
                    continue
                best = min(seeds, key=lambda s: (s[0] - x) ** 2 + (s[1] - y) ** 2)
                _, _, biome = best
                dom, secondary, _, _ = self.BIOMES[biome]
                t = secondary if rng.random() < 0.1 else dom
                out.append({"x": x, "y": y, "terrain": t, "is_wall": False, "difficult": False})
                tile_biome[(x, y)] = biome

        # World decorations: a few prominent landmarks per region. Trees in forest
        # regions, cacti in desert, etc. Sparse — this is an overworld, not a
        # detailed scene.
        decorations = []
        kind_for_biome = {
            "forest": "TREE", "plains": "BUSH", "desert": "CACTUS",
            "coastal": "ROCK", "tundra": "ROCK", "town": "BANNER",
        }
        candidates = list(tile_biome.keys())
        rng.shuffle(candidates)
        target = int(w * h * 0.025)  # ~2.5% density
        for (cx, cy) in candidates[:target]:
            biome = tile_biome[(cx, cy)]
            decorations.append({"x": cx, "y": cy, "kind": kind_for_biome.get(biome, "ROCK")})
        return out, decorations

    def generate_starter_world(
        self,
        campaign_id: uuid.UUID,
        seed: int = 42,
    ) -> dict:
        """Build a full World → Area → Room set for a brand-new campaign.

        Layout:
        - 1 World map (40×40, biomes, no walls)
        - 1 Area map under it (24×24, mixed terrain, no walls)
        - 1 Room map under the Area (20×20, room-style with walls)

        Subsequent generation can add sibling areas/rooms; this just gives the
        user something to land on at session start.
        """
        import random

        rng = random.Random(seed)

        world = self.generate_map(
            campaign_id=campaign_id,
            name="World Map",
            width=40,
            height=40,
            seed=rng.randrange(1, 2**31),
            kind="WORLD",
        )
        # Starting areas default to a plains/forest biome — a believable
        # "first place a campaign opens on." Caller can override.
        area_biome = rng.choice(["plains", "forest"])
        area = self.generate_map(
            campaign_id=campaign_id,
            name="Starting Area",
            width=24,
            height=24,
            seed=rng.randrange(1, 2**31),
            kind="AREA",
            parent_map_id=uuid.UUID(world["map_id"]),
            biome=area_biome,
        )
        room = self.generate_map(
            campaign_id=campaign_id,
            name="Starting Room",
            width=20,
            height=20,
            seed=rng.randrange(1, 2**31),
            kind="ROOM",
            parent_map_id=uuid.UUID(area["map_id"]),
        )
        return {"world": world, "area": area, "room": room}
