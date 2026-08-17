from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from persona.models import PersonaBlueprint, PersonaVersionRecord


class PersonaVersioning:
    VERSION = "persona-versioning-1.0.0"

    @staticmethod
    def record(
        blueprint: PersonaBlueprint,
        *,
        parent_version_id: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ) -> PersonaVersionRecord:
        encoded = json.dumps(
            blueprint.model_dump(mode="json", exclude={"validation": {"warnings"}}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        content_hash = hashlib.sha256(encoded).hexdigest()
        version_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:persona-version:{blueprint.persona_id}:"
            f"{blueprint.schema_version}:{content_hash}:{parent_version_id}",
        )
        return PersonaVersionRecord(
            version_id=version_id,
            blueprint=blueprint,
            content_hash=content_hash,
            parent_version_id=parent_version_id,
            created_at=created_at or datetime.now(UTC),
        )
