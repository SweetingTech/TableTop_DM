import uuid

import pytest

from services.domain.maps import system as maps_module
from services.domain.maps.system import MapSystem, ProceduralMapGenerator

pytestmark = pytest.mark.unit


class FakeCursor:
    def __init__(self):
        self.execute_calls = []
        self.closed = False

    def execute(self, query, params):
        self.execute_calls.append((query, params))

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_bulk_set_map_nodes_uses_one_values_statement(monkeypatch):
    connection = FakeConnection()
    execute_values_calls = []
    map_id = uuid.uuid4()

    monkeypatch.setattr(
        "psycopg2.extras.execute_values",
        lambda cursor, query, data, template: execute_values_calls.append(
            (cursor, query, data, template)
        ),
    )

    result = MapSystem().bulk_set_map_nodes(
        [
            {
                "map_id": map_id,
                "tier": 0,
                "x": 1,
                "y": 2,
                "collision_mask": "0" * 16,
                "terrain": {"type": "grass"},
            },
            {
                "map_id": map_id,
                "tier": 0,
                "x": 2,
                "y": 2,
                "collision_mask": "1" + "0" * 15,
                "terrain": None,
            },
        ],
        conn=connection,
    )

    assert result == {"success": True, "count": 2}
    assert len(execute_values_calls) == 1
    cursor, query, data, template = execute_values_calls[0]
    assert cursor is connection.cursor_instance
    assert "ON CONFLICT (map_id, tier, x, y)" in query
    assert template.endswith("%s::jsonb)")
    assert len(data) == 2
    assert data[0][1:] == (
        str(map_id),
        0,
        1,
        2,
        "0" * 16,
        '{"type": "grass"}',
    )
    assert data[1][-1] == "{}"
    assert connection.commits == 0
    assert connection.cursor_instance.closed is True


def test_generate_map_bulk_inserts_composed_tiles(monkeypatch):
    connection = FakeConnection()
    campaign_id = uuid.uuid4()
    map_id = uuid.uuid4()
    bulk_calls = []

    monkeypatch.setattr(maps_module, "get_connection", lambda: connection)
    monkeypatch.setattr(
        MapSystem,
        "create_map",
        lambda *_args, **_kwargs: {
            "map_id": str(map_id),
            "name": "Test Room",
            "kind": "ROOM",
        },
    )
    monkeypatch.setattr(
        MapSystem,
        "bulk_set_map_nodes",
        lambda _self, nodes, conn: bulk_calls.append((nodes, conn))
        or {"success": True, "count": len(nodes)},
    )
    monkeypatch.setattr(
        MapSystem,
        "set_map_node",
        lambda *_args, **_kwargs: pytest.fail("per-tile insert should not be used"),
    )
    monkeypatch.setattr(
        ProceduralMapGenerator,
        "_compose_room",
        lambda *_args, **_kwargs: (
            [
                {
                    "x": 0,
                    "y": 0,
                    "terrain": "stone_floor",
                    "is_wall": True,
                    "difficult": False,
                },
                {
                    "x": 1,
                    "y": 0,
                    "terrain": "grass",
                    "is_wall": False,
                    "difficult": True,
                },
            ],
            [],
        ),
    )

    result = ProceduralMapGenerator().generate_map(
        campaign_id,
        "Test Room",
        width=2,
        height=1,
    )

    assert result["map_id"] == str(map_id)
    assert len(bulk_calls) == 1
    nodes, used_connection = bulk_calls[0]
    assert used_connection is connection
    assert [node["terrain"] for node in nodes] == [
        {"type": "wall", "difficult": False},
        {"type": "grass", "difficult": True},
    ]
    assert connection.commits == 1
    assert connection.closed is True
