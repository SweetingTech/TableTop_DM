import uuid
import heapq
import math
from typing import Optional
from shared.schemas.events import StateDelta, ToolCallPayload


class GridCell:
    def __init__(self, x: int, y: int, walkable: bool = True, difficult: bool = False):
        self.x = x
        self.y = y
        self.walkable = walkable
        self.difficult = difficult

    @property
    def cost(self) -> float:
        return 2.0 if self.difficult else 1.0


class SpatialEngine:
    def __init__(self):
        self._grids: dict[str, dict[tuple[int, int], GridCell]] = {}

    def load_grid(self, map_id: str, cells: list[dict]) -> None:
        grid = {}
        for cell in cells:
            x, y = cell["x"], cell["y"]
            collision = cell.get("collision_mask", "0" * 16)
            walkable = collision[0] == "0" if isinstance(collision, str) else True
            terrain = cell.get("terrain", {})
            difficult = (
                terrain.get("difficult", False) if isinstance(terrain, dict) else False
            )
            grid[(x, y)] = GridCell(x, y, walkable, difficult)
        self._grids[map_id] = grid

    def load_grid_from_db(self, map_id: str) -> None:
        from shared.db.connection import execute_query, execute_one

        map_row = execute_one(
            "SELECT width, height FROM state.maps WHERE id = %s", (map_id,)
        )
        if not map_row:
            return

        nodes = execute_query(
            "SELECT x, y, collision_mask, terrain FROM state.map_nodes WHERE map_id = %s",
            (map_id,),
        )

        cells = []
        for n in nodes:
            mask = n["collision_mask"]
            if isinstance(mask, (bytes, memoryview)):
                mask_str = format(int.from_bytes(bytes(mask), "big"), "016b")
            else:
                mask_str = str(mask)
            cells.append(
                {
                    "x": n["x"],
                    "y": n["y"],
                    "collision_mask": mask_str,
                    "terrain": n["terrain"],
                }
            )

        w, h = map_row["width"], map_row["height"]
        existing = {(c["x"], c["y"]) for c in cells}
        for x in range(w):
            for y in range(h):
                if (x, y) not in existing:
                    cells.append(
                        {"x": x, "y": y, "collision_mask": "0" * 16, "terrain": {}}
                    )

        self.load_grid(map_id, cells)

    def _get_grid(self, map_id: str) -> dict[tuple[int, int], GridCell]:
        if map_id not in self._grids:
            self.load_grid_from_db(map_id)
        return self._grids.get(map_id, {})

    def _neighbors(self, grid: dict, x: int, y: int) -> list[tuple[int, int]]:
        result = []
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            cell = grid.get((nx, ny))
            if cell and cell.walkable:
                result.append((nx, ny))
        return result

    def compute_path(
        self, map_id: str, start_x: int, start_y: int, end_x: int, end_y: int
    ) -> Optional[list[tuple[int, int]]]:
        grid = self._get_grid(map_id)
        if not grid:
            return None

        start = (start_x, start_y)
        end = (end_x, end_y)

        if start not in grid or end not in grid:
            return None
        if not grid[start].walkable or not grid[end].walkable:
            return None

        def heuristic(a, b):
            return abs(a[0] - b[0]) + abs(a[1] - b[1])

        open_set = [(0, start)]
        came_from = {}
        g_score = {start: 0.0}
        f_score = {start: heuristic(start, end)}

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == end:
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                return path

            for neighbor in self._neighbors(grid, current[0], current[1]):
                cell = grid[neighbor]
                tentative = g_score[current] + cell.cost

                if tentative < g_score.get(neighbor, float("inf")):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative
                    f_score[neighbor] = tentative + heuristic(neighbor, end)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        return None

    def move_entity(
        self,
        entity_id: uuid.UUID,
        map_id: str,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        max_speed: int,
        grid_size: int = 5,
    ) -> ToolCallPayload:
        path = self.compute_path(map_id, from_x, from_y, to_x, to_y)

        if path is None:
            return ToolCallPayload(
                tool_name="move_entity",
                arguments={"entity_id": str(entity_id), "to_x": to_x, "to_y": to_y},
                result={"success": False, "reason": "No valid path"},
                deltas=[],
            )

        grid = self._get_grid(map_id)
        total_cost = 0.0
        for pos in path[1:]:
            cell = grid.get(pos)
            total_cost += (cell.cost if cell else 1.0) * grid_size

        max_distance = max_speed
        if total_cost > max_distance:
            return ToolCallPayload(
                tool_name="move_entity",
                arguments={"entity_id": str(entity_id), "to_x": to_x, "to_y": to_y},
                result={
                    "success": False,
                    "reason": f"Path cost {total_cost}ft exceeds speed {max_distance}ft",
                },
                deltas=[],
            )

        deltas = [
            StateDelta(
                table="state.entity_positions",
                operation="UPDATE",
                entity_id=entity_id,
                changes={
                    "x": to_x,
                    "y": to_y,
                    "previous_x": from_x,
                    "previous_y": from_y,
                },
                domain_tags=["movement"],
            )
        ]

        return ToolCallPayload(
            tool_name="move_entity",
            arguments={"entity_id": str(entity_id), "to_x": to_x, "to_y": to_y},
            result={
                "success": True,
                "entity_id": str(entity_id),
                "path": path,
                "distance_ft": total_cost,
            },
            deltas=deltas,
        )

    def check_line_of_sight(
        self, map_id: str, x1: int, y1: int, x2: int, y2: int
    ) -> dict:
        grid = self._get_grid(map_id)
        if not grid:
            return {"clear": False, "reason": "no_grid"}

        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy

        x, y = x1, y1
        blockers = []

        while True:
            if (x, y) != (x1, y1) and (x, y) != (x2, y2):
                cell = grid.get((x, y))
                if cell and not cell.walkable:
                    blockers.append((x, y))

            if x == x2 and y == y2:
                break

            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

        return {
            "clear": len(blockers) == 0,
            "from": (x1, y1),
            "to": (x2, y2),
            "blockers": blockers,
            "distance": math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2),
        }

    def check_threat_radius(
        self,
        map_id: str,
        entity_x: int,
        entity_y: int,
        trigger_x: int,
        trigger_y: int,
        radius: int = 1,
    ) -> bool:
        distance = abs(entity_x - trigger_x) + abs(entity_y - trigger_y)
        return distance <= radius
