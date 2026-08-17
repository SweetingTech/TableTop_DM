import pytest

from persona.compilation import PersonaCompiler
from persona.generation import PersonaGenerator
from persona.registry import PersonaSchemaRegistry

pytestmark = pytest.mark.unit


def test_default_registry_contains_eighty_dimensions():
    registry = PersonaSchemaRegistry.load_default()
    assert len(registry.dimensions) == 80


def test_seed_and_fixed_dimensions_are_reproducible():
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())
    fixed = {"rules_familiarity": "LOW", "player_style": "EXPLORER"}
    first = generator.generate(4815162342, fixed)
    second = generator.generate(4815162342, fixed)
    assert first == second
    assert first.validation.status == "valid"
    assert first.dimensions["rules_familiarity"] == "LOW"
    assert first.provenance["rules_familiarity"]["source"] == "fixed"


def test_compiler_keeps_runtime_out_of_identity():
    persona = PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(42)
    compiled = PersonaCompiler().compile(persona)
    assert compiled.persona_id == persona.persona_id
    assert "runtime" not in compiled.model_dump()
    assert 0 <= compiled.policy_weights["rules_familiarity"] <= 1
