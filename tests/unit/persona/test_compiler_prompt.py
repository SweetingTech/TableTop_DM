from __future__ import annotations

import pytest

from persona.compilation import PersonaCompiler
from persona.generation import PersonaGenerator
from persona.registry import PersonaSchemaRegistry

pytestmark = pytest.mark.unit


def test_compiler_emits_behavioral_seeds_and_capability_modifiers():
    persona = PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(
        9,
        fixed={
            "risk_tolerance": "LOW",
            "authority_trust": "LOW",
            "rules_familiarity": "HIGH",
            "reading_tolerance": "LOW",
        },
    )
    compiled = PersonaCompiler().compile(persona)

    assert compiled.starting_beliefs
    assert compiled.starting_relationships
    assert compiled.routines
    assert compiled.capability_modifiers["rules.interpret"] == 0.9
    assert compiled.capability_modifiers["text.process"] == 0.25
    assert compiled.deep_traits["risk_tolerance"] == "LOW"


def test_prompt_assembly_fetches_only_relevant_traits_and_honors_both_budgets():
    compiler = PersonaCompiler()
    compiled = compiler.compile(PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(22))

    prompt = compiler.assemble_prompt(
        compiled,
        situation_summary="A merchant is offering medicine at an alarming price.",
        relevant_traits=("risk_tolerance", "family_loyalty", "does_not_exist"),
        max_tokens=24,
        max_characters=80,
    )
    repeated = compiler.assemble_prompt(
        compiled,
        situation_summary="A merchant is offering medicine at an alarming price.",
        relevant_traits=("family_loyalty", "risk_tolerance"),
        max_tokens=24,
        max_characters=80,
    )

    assert prompt == repeated
    assert prompt.character_count <= 80
    assert prompt.estimated_tokens <= 24
    assert prompt.included_traits == ("family_loyalty", "risk_tolerance")
    assert prompt.truncated is True


def test_prompt_budget_must_be_positive():
    compiled = PersonaCompiler().compile(
        PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(1)
    )
    with pytest.raises(ValueError, match="budgets must be positive"):
        PersonaCompiler.assemble_prompt(compiled, max_tokens=0)
