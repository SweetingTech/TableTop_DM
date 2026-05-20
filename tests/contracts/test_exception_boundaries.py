from __future__ import annotations

import ast
from pathlib import Path


ROUTE_BOUNDARY_FILES = [
    Path("app.py"),
    Path("services/api/application.py"),
]


def test_route_layer_broad_exception_boundaries_are_explicit() -> None:
    offenders: list[str] = []
    for path in ROUTE_BOUNDARY_FILES:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = node.type
            catches_exception = (
                caught is None
                or (isinstance(caught, ast.Name) and caught.id == "Exception")
                or (
                    isinstance(caught, ast.Tuple)
                    and any(
                        isinstance(elt, ast.Name) and elt.id == "Exception"
                        for elt in caught.elts
                    )
                )
            )
            if not catches_exception:
                continue
            line = lines[node.lineno - 1]
            previous = lines[node.lineno - 2] if node.lineno >= 2 else ""
            if (
                "# defensive boundary" not in line
                and "# defensive boundary" not in previous
            ):
                offenders.append(f"{path}:{node.lineno}")

    assert offenders == []
