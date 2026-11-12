from __future__ import annotations

import pytest

from persona.compilation import PersonaCompiler
from persona.generation import PersonaGenerator
from persona.models import PersonaPurpose
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


def test_character_compilation_excludes_playtester_traits_and_behavior():
    registry = PersonaSchemaRegistry.load_default()
    blueprint = PersonaGenerator(registry).generate(9, purpose=PersonaPurpose.CHARACTER)
    compiler = PersonaCompiler()
    compiled = compiler.compile(blueprint)
    excluded = {
        name
        for name, spec in registry.dimensions.items()
        if spec.domain_pack in {"tabletop", "accessibility"}
    }
    assert compiled.purpose == PersonaPurpose.CHARACTER
    assert excluded.isdisjoint(compiled.deep_traits)
    assert not compiled.starting_goals
    assert not compiled.starting_relationships
    assert not compiled.retrieval_filters
    assert not compiled.capability_modifiers
    assert not blueprint.derived_traits
    assert "player" not in compiled.identity_summary
    assert "rules_familiarity" not in compiled.policy_weights

    # Even an imported compiled record cannot reinsert excluded/unknown trait keys.
    contaminated = compiled.model_copy(
        update={
            "deep_traits": {
                **compiled.deep_traits,
                **{name: "PRIVATE_PLAYER_METADATA" for name in excluded},
                "unknown_operator_note": "PRIVATE_PLAYER_METADATA",
            }
        }
    )
    prompt = compiler.assemble_prompt(
        contaminated,
        relevant_traits=tuple(contaminated.deep_traits),
        max_tokens=8000,
        max_characters=32000,
    )
    assert excluded.isdisjoint(prompt.included_traits)
    assert "unknown_operator_note" not in prompt.included_traits
    assert "PRIVATE_PLAYER_METADATA" not in prompt.text
    assert "risk_tolerance" in prompt.included_traits


def test_character_behavior_is_invariant_to_player_metadata_but_uses_world_traits():
    registry = PersonaSchemaRegistry.load_default()
    blueprint = PersonaGenerator(registry).generate(17, purpose=PersonaPurpose.CHARACTER)
    compiler = PersonaCompiler()
    changed = blueprint.model_copy(
        update={
            "dimensions": {
                name: (
                    "IGNORED_PLAYER_METADATA"
                    if spec.domain_pack in {"tabletop", "accessibility"}
                    else blueprint.dimensions.get(name)
                )
                for name, spec in registry.dimensions.items()
                if name in blueprint.dimensions
            }
        }
    )
    first, second = compiler.compile(blueprint), compiler.compile(changed)
    assert first.model_dump(exclude={"persona_version"}) == second.model_dump(
        exclude={"persona_version"}
    )
    assert compiler.assemble_prompt(
        first, relevant_traits=tuple(registry.dimensions)
    ) == compiler.assemble_prompt(second, relevant_traits=tuple(registry.dimensions))
    alternate = "LOW" if blueprint.dimensions["risk_tolerance"] != "LOW" else "HIGH"
    different = compiler.compile(
        blueprint.model_copy(
            update={
                "dimensions": {
                    **blueprint.dimensions,
                    "risk_tolerance": alternate,
                }
            }
        )
    )
    assert different.policy_weights["risk_penalty"] != first.policy_weights["risk_penalty"]
    assert different.identity_summary != first.identity_summary


def test_playtester_default_retains_evaluation_behavior():
    compiled = PersonaCompiler().compile(
        PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(9)
    )
    assert compiled.purpose == PersonaPurpose.SIMULATED_PLAYTESTER
    assert "player" in compiled.identity_summary
    assert "finish_onboarding" in compiled.starting_goals
    assert compiled.starting_relationships[0]["target_role"] == "GM"
    assert "interface.navigate" in compiled.capability_modifiers
