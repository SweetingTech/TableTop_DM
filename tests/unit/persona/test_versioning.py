from __future__ import annotations

import hashlib
import json
import uuid

import pytest

from persona.generation import PersonaGenerator
from persona.models import PersonaBlueprint, PersonaPurpose
from persona.registry import PersonaSchemaRegistry
from persona.versioning import PersonaVersioning

pytestmark = pytest.mark.unit


def test_legacy_persona_identity_and_hash_survive_explicit_default_purpose():
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())
    persona = generator.generate(17)
    old_document = persona.model_dump(mode="json", exclude={"purpose"})
    restored = PersonaBlueprint.model_validate(old_document)
    assert restored == persona
    assert generator.generate(17, purpose=PersonaPurpose.SIMULATED_PLAYTESTER) == persona
    key = json.dumps(
        {"fixed": {}, "distributions": {}, "use_defaults": False, "generator": generator.VERSION},
        sort_keys=True,
        separators=(",", ":"),
    )
    assert persona.persona_id == uuid.uuid5(
        uuid.NAMESPACE_URL, f"tabletop-dm:persona:2.0.0:17:{key}"
    )
    old_document["validation"].pop("warnings")
    historical_hash = hashlib.sha256(
        json.dumps(old_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    record = PersonaVersioning.record(restored)
    assert record.content_hash == historical_hash
    assert record.version_id == uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"tabletop-dm:persona-version:{persona.persona_id}:2.0.0:{historical_hash}:None",
    )


def test_character_purpose_has_reproducible_distinct_identity_and_version():
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())
    character = generator.generate(17, purpose=PersonaPurpose.CHARACTER)
    player = generator.generate(17)
    assert character == generator.generate(17, purpose=PersonaPurpose.CHARACTER)
    assert character.persona_id != player.persona_id
    assert (
        PersonaVersioning.record(character).version_id
        == PersonaVersioning.record(character).version_id
    )
    same_identity = character.model_copy(update={"persona_id": player.persona_id})
    assert (
        PersonaVersioning.record(same_identity).content_hash
        != PersonaVersioning.record(player).content_hash
    )
    with pytest.raises(ValueError):
        generator.generate(17, purpose="NOT_A_PURPOSE")
