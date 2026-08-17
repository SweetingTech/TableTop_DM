from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from experiments.models import ArtifactReference


class LocalArtifactStore:
    """Content-addressed local JSON artifacts published with atomic replacement."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write_json(self, kind: str, key: str, payload: dict[str, Any]) -> ArtifactReference:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        content_hash = hashlib.sha256(encoded).hexdigest()
        artifact_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:artifact:{kind}:{key}:{content_hash}",
        )
        safe_kind = self._safe_component(kind)
        safe_key = self._safe_component(key)
        destination = self.root / safe_kind / f"{safe_key}-{content_hash[:16]}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(encoded)
            os.replace(temporary, destination)
        return ArtifactReference(
            artifact_id=artifact_id,
            kind=kind,
            uri=destination.as_uri(),
            content_hash=content_hash,
        )

    @staticmethod
    def read(reference: ArtifactReference) -> dict[str, Any]:
        path = Path(reference.uri.removeprefix("file:///"))
        if not path.exists() and reference.uri.startswith("file:///"):
            path = Path("/" + reference.uri.removeprefix("file:///"))
        encoded = path.read_bytes()
        if hashlib.sha256(encoded).hexdigest() != reference.content_hash:
            raise ValueError("Artifact content hash mismatch")
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise TypeError("JSON artifact root must be an object")
        return payload

    @staticmethod
    def _safe_component(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in {"-", "_", "."} else "-"
            for character in value
        ).strip(".-")
        if not safe:
            raise ValueError("Artifact path component cannot be empty")
        return safe[:120]
