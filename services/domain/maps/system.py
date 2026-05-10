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
    TERRAIN_TYPES = ["stone_floor", "grass", "dirt", "water", "sand", "wood"]
    # Terrain palettes specialised by tier so a world map doesn't look like a
    # tactical room. World tiles read as biomes (mostly walkable open ground);
    # areas blend (town / wilderness mix); rooms are the existing room-flavor.
    WORLD_TERRAIN = ["grass", "dirt", "sand", "water"]
    AREA_TERRAIN = ["stone_floor", "grass", "dirt", "wood", "sand"]

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
    ) -> dict:
        import random

        rng = random.Random(seed)
        terrain_pool = {
            "WORLD": self.WORLD_TERRAIN,
            "AREA": self.AREA_TERRAIN,
            "ROOM": self.TERRAIN_TYPES,
        }.get(kind, self.TERRAIN_TYPES)
        # World maps are open with sparse obstacles; rooms have walls + clutter.
        obstacle_rate = {"WORLD": 0.05, "AREA": 0.08, "ROOM": 0.15}.get(kind, 0.15)
        wall_borders = kind == "ROOM"

        map_system = MapSystem()
        result = map_system.create_map(
            campaign_id, name, width, height, grid_size, kind, parent_map_id
        )
        map_id = uuid.UUID(result["map_id"])

        conn = get_connection()
        try:
            for y in range(height):
                for x in range(width):
                    is_wall = wall_borders and (
                        x == 0 or y == 0 or x == width - 1 or y == height - 1
                    )
                    is_obstacle = rng.random() < obstacle_rate if not is_wall else False

                    walkable = not (is_wall or is_obstacle)
                    collision = "0" * 16 if walkable else "1" + "0" * 15

                    terrain_type = rng.choice(terrain_pool) if walkable else "wall"
                    difficult = rng.random() < 0.1

                    map_system.set_map_node(
                        map_id,
                        0,
                        x,
                        y,
                        collision,
                        {"type": terrain_type, "difficult": difficult},
                        conn,
                    )

            conn.commit()
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
        }

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
        area = self.generate_map(
            campaign_id=campaign_id,
            name="Starting Area",
            width=24,
            height=24,
            seed=rng.randrange(1, 2**31),
            kind="AREA",
            parent_map_id=uuid.UUID(world["map_id"]),
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
