from __future__ import annotations

from pathlib import Path


def test_every_registered_route_is_listed_in_auth_matrix() -> None:
    from app import app

    matrix = Path("docs/release/1.0-route-auth-matrix.md").read_text(encoding="utf-8")
    missing: list[str] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        route = str(rule)
        if f"`{route}`" not in matrix:
            missing.append(route)

    assert missing == []
