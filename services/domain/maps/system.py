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
                INSERT INTO state.maps (id, campaign_id, name, width, height, grid_size)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (str(map_id), str(campaign_id), name, width, height, grid_size),
            )

            if own_conn:
                conn.commit()
            cur.close()
            return {"map_id": str(map_id), "name": name}
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

    def generate_map(
        self,
        campaign_id: uuid.UUID,
        name: str,
        width: int,
        height: int,
        seed: int = 42,
        grid_size: int = 5,
    ) -> dict:
        import random

        rng = random.Random(seed)

        map_system = MapSystem()
        result = map_system.create_map(campaign_id, name, width, height, grid_size)
        map_id = uuid.UUID(result["map_id"])

        conn = get_connection()
        try:
            for y in range(height):
                for x in range(width):
                    is_wall = x == 0 or y == 0 or x == width - 1 or y == height - 1
                    is_obstacle = rng.random() < 0.15 if not is_wall else False

                    walkable = not (is_wall or is_obstacle)
                    collision = "0" * 16 if walkable else "1" + "0" * 15

                    terrain_type = (
                        rng.choice(self.TERRAIN_TYPES) if walkable else "wall"
                    )
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
        }
