from __future__ import annotations

from datetime import UTC, datetime

import pytest

from persona.errors import FixedFieldFeasibilityError, InfeasibleStratumError
from persona.generation import PersonaGenerator
from persona.registry import PersonaSchemaRegistry
from persona.validation import PersonaValidator
from persona.versioning import PersonaVersioning

pytestmark = pytest.mark.unit


def test_default_registry_has_exactly_80_versioned_pack_dimensions():
    registry = PersonaSchemaRegistry.load_default()

    assert len(registry.dimensions) == 80
    assert set(registry.domain_packs) == {
        "core",
        "world",
        "tabletop",
        "accessibility",
    }
    assert all(spec.domain_pack in registry.domain_packs for spec in registry.dimensions.values())
    defaults = registry.defaults()
    assert len(defaults) == 80
    assert PersonaValidator(registry).validate_dimensions(defaults).status == "valid"


def test_seeded_weighted_generation_is_reproducible_valid_and_provenanced():
    registry = PersonaSchemaRegistry.load_default()
    generator = PersonaGenerator(registry)
    distributions = {
        "species": {"ELF": 1},
        "lifespan_band": {"LONG": 3, "VERY_LONG": 1},
        "player_style": {"EXPLORER": 4, "BALANCED": 1},
    }

    first = generator.generate(
        481516,
        fixed={"social_class": "ELITE"},
        distributions=distributions,
    )
    second = generator.generate(
        481516,
        fixed={"social_class": "ELITE"},
        distributions=distributions,
    )

    assert first == second
    assert first.validation.status == "valid"
    assert first.dimensions["species"] == "ELF"
    assert first.dimensions["lifespan_band"] in {"LONG", "VERY_LONG"}
    assert first.dimensions["property_access"] not in {"NONE", "SHARED"}
    assert first.provenance["social_class"].source == "fixed"
    assert first.provenance["species"].source == "weighted_distribution"
    assert first.provenance["species"].domain_pack == "world"


def test_defaults_are_explicit_and_fixed_infeasibility_is_not_silently_dropped():
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())
    defaulted = generator.generate(5, use_defaults=True)

    assert defaulted.dimensions["decision_style"] == "DELIBERATIVE"
    assert defaulted.provenance["decision_style"].source == "default"
    with pytest.raises(FixedFieldFeasibilityError, match="literacy is inactive"):
        generator.generate(
            5,
            fixed={"education_access": "NONE", "literacy": "FLUENT"},
        )
    with pytest.raises(FixedFieldFeasibilityError, match="Elven personas"):
        generator.generate(
            5,
            fixed={"species": "ELF", "lifespan_band": "HUMANLIKE"},
        )
    report = generator.validate_stratum({"species": "ELF", "lifespan_band": "HUMANLIKE"})
    assert report.feasible is False
    assert report.errors


def test_fixed_or_distributed_children_constrain_upstream_dependencies_and_rules():
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())

    for seed in range(20):
        persona = generator.generate(seed, fixed={"literacy": "FLUENT"})
        assert persona.dimensions["education_access"] != "NONE"

    infeasible = generator.validate_stratum(
        {},
        distributions={
            "species": {"ELF": 1},
            "lifespan_band": {"HUMANLIKE": 1},
        },
    )
    assert infeasible.feasible is False
    assert "No feasible weighted value for species" in infeasible.errors[0]


def test_validator_reports_unknown_inactive_and_incompatible_dimensions():
    registry = PersonaSchemaRegistry.load_default()
    values = registry.defaults()
    values.update(
        {
            "education_access": "NONE",
            "literacy": "FLUENT",
            "occupation_sector": "SCHOLARLY",
            "not_a_dimension": True,
        }
    )

    validation = PersonaValidator(registry).validate_dimensions(values)

    assert validation.status == "invalid"
    assert any("Unknown dimensions" in error for error in validation.errors)
    assert any("literacy is inactive" in error for error in validation.errors)
    assert any("scholarly_education_access" in error for error in validation.errors)


def test_persona_versions_are_content_addressed_and_parent_sensitive():
    persona = PersonaGenerator(PersonaSchemaRegistry.load_default()).generate(17)
    timestamp = datetime(2040, 1, 1, tzinfo=UTC)

    first = PersonaVersioning.record(persona, created_at=timestamp)
    repeated = PersonaVersioning.record(persona, created_at=timestamp)
    child = PersonaVersioning.record(
        persona,
        parent_version_id=first.version_id,
        created_at=timestamp,
    )

    assert first == repeated
    assert len(first.content_hash) == 64
    assert child.version_id != first.version_id
    assert child.parent_version_id == first.version_id


@pytest.mark.parametrize(
    "weight", [float("nan"), float("inf"), float("-inf"), pytest.param(10**400, id="overflow")]
)
def test_nonfinite_distribution_weights_fail_with_feasibility_error(weight):
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())
    distribution = {"risk_tolerance": {"LOW": weight, "HIGH": 1.0}}
    with pytest.raises(InfeasibleStratumError, match="finite non-negative"):
        generator.generate(17, distributions=distribution)
    report = generator.validate_stratum({}, distributions=distribution)
    assert report.feasible is False
    assert "finite non-negative" in report.errors[0]


def test_finite_weights_with_overflowing_total_fail_before_sampling():
    generator = PersonaGenerator(PersonaSchemaRegistry.load_default())
    with pytest.raises(InfeasibleStratumError, match="total weight must be finite"):
        generator.generate(17, distributions={"risk_tolerance": {"LOW": 1e308, "HIGH": 1e308}})
    first = generator.generate(17, distributions={"risk_tolerance": {"LOW": 1e308}})
    assert first == generator.generate(17, distributions={"risk_tolerance": {"LOW": 1e308}})
    assert first.dimensions["risk_tolerance"] == "LOW"
