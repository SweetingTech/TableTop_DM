from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from kernel.state import stable_hash


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    through_event_seq: int
    state_hash: str
    artifact_uri: str
    artifact_hash: str
    contract_version: str = "2.0.0"


class SnapshotStore:
    """Content-addressed local artifact store with deterministic gzip bundles."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def create(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        through_event_seq: int,
        projections: dict[str, Any],
    ) -> SnapshotManifest:
        state_hash = stable_hash(projections)
        snapshot_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:snapshot:{world_id}:{branch_id}:{through_event_seq}:{state_hash}",
        )
        body = json.dumps(
            {
                "snapshot_id": str(snapshot_id),
                "world_id": str(world_id),
                "branch_id": str(branch_id),
                "through_event_seq": through_event_seq,
                "contract_version": "2.0.0",
                "state_hash": state_hash,
                "projections": projections,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        compressed = gzip.compress(body, mtime=0)
        artifact_hash = hashlib.sha256(compressed).hexdigest()
        destination = self.root / str(world_id) / f"{snapshot_id}.json.gz"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(compressed)
        os.replace(temporary, destination)
        return SnapshotManifest(
            snapshot_id=snapshot_id,
            world_id=world_id,
            branch_id=branch_id,
            through_event_seq=through_event_seq,
            state_hash=state_hash,
            artifact_uri=destination.as_uri(),
            artifact_hash=artifact_hash,
        )

    @staticmethod
    def load(manifest: SnapshotManifest) -> dict[str, Any]:
        path = Path(manifest.artifact_uri.removeprefix("file:///"))
        if not path.exists() and manifest.artifact_uri.startswith("file:///"):
            path = Path("/" + manifest.artifact_uri.removeprefix("file:///"))
        compressed = path.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != manifest.artifact_hash:
            raise ValueError("Snapshot artifact hash mismatch")
        payload = json.loads(gzip.decompress(compressed))
        if stable_hash(payload["projections"]) != manifest.state_hash:
            raise ValueError("Snapshot state hash mismatch")
        return payload
