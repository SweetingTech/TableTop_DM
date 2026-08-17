from __future__ import annotations

import json
import random
import uuid
from collections.abc import Iterator
from typing import Any, Literal

from persona.errors import FixedFieldFeasibilityError, InfeasibleStratumError
from persona.models import FieldProvenance, PersonaBlueprint, StratumFeasibility
from persona.registry import PersonaSchemaRegistry
from persona.validation import PersonaValidator

ProvenanceSource = Literal["fixed", "default", "seeded_generator", "weighted_distribution"]


class PersonaGenerator:
    VERSION = "persona-gen-0.2.0"

    def __init__(self, registry: PersonaSchemaRegistry) -> None:
        self.registry = registry
        self.validator = PersonaValidator(registry)

    def generate(
        self,
        seed: int,
        fixed: dict[str, Any] | None = None,
        distributions: dict[str, dict[Any, float]] | None = None,
        *,
        use_defaults: bool = False,
    ) -> PersonaBlueprint:
        fixed = fixed or {}
        distributions = distributions or {}
        unknown = set(fixed) - set(self.registry.dimensions)
        if unknown:
            raise FixedFieldFeasibilityError(f"Unknown fixed dimensions: {sorted(unknown)}")
        unknown_distributions = set(distributions) - set(self.registry.dimensions)
        if unknown_distributions:
            raise InfeasibleStratumError(
                f"Unknown distribution dimensions: {sorted(unknown_distributions)}"
            )
        overlap = set(fixed) & set(distributions)
        if overlap:
            raise InfeasibleStratumError(
                f"Dimensions cannot be both fixed and distributed: {sorted(overlap)}"
            )
        self._validate_fixed_assignments(fixed)

        rng = random.Random(seed)
        values: dict[str, Any] = {}
        provenance: dict[str, FieldProvenance] = {}
        for spec in self.registry.ordered_dimensions():
            enabled = self.registry.is_enabled(spec, values)
            if not enabled:
                if spec.name in fixed:
                    raise FixedFieldFeasibilityError(
                        f"Fixed dimension {spec.name} is inactive for dependencies "
                        f"{spec.depends_on} under assignments {values}"
                    )
                if spec.name in distributions:
                    raise InfeasibleStratumError(
                        f"Distribution dimension {spec.name} is inactive for dependencies "
                        f"{spec.depends_on} under assignments {values}"
                    )
                continue

            source: ProvenanceSource
            if spec.name in fixed:
                value = fixed[spec.name]
                source = "fixed"
            elif use_defaults:
                value = spec.default
                source = "default"
            elif spec.kind == "boolean":
                value, source = self._choose(
                    rng,
                    spec.name,
                    (False, True),
                    values,
                    fixed,
                    distributions,
                )
            elif spec.kind == "enum":
                value, source = self._choose(
                    rng,
                    spec.name,
                    spec.values,
                    values,
                    fixed,
                    distributions,
                )
            elif spec.kind == "integer":
                value = rng.randint(int(spec.minimum or 0), int(spec.maximum or 100))
                source = "seeded_generator"
            else:
                minimum = float(spec.minimum or 0)
                maximum = float(spec.maximum or 1)
                value = round(rng.uniform(minimum, maximum), 4)
                source = "seeded_generator"

            error = self.registry.validate_value(spec, value)
            if error:
                error_type = (
                    FixedFieldFeasibilityError if spec.name in fixed else InfeasibleStratumError
                )
                raise error_type(error)
            values[spec.name] = value
            constraint_errors = self.registry.constraint_errors(values, partial=True)
            if constraint_errors:
                values.pop(spec.name)
                error_type = (
                    FixedFieldFeasibilityError if spec.name in fixed else InfeasibleStratumError
                )
                raise error_type("; ".join(constraint_errors))
            provenance[spec.name] = FieldProvenance(
                source=source,
                generator_version=self.VERSION,
                schema_version=self.registry.VERSION,
                domain_pack=spec.domain_pack,
                seed=seed,
                distribution={
                    str(key): float(weight)
                    for key, weight in distributions.get(spec.name, {}).items()
                },
                constraint_rules=tuple(
                    rule.rule_id
                    for rule in self.registry.constraints
                    if spec.name in rule.when
                    or spec.name in rule.require
                    or spec.name in rule.forbid
                ),
            )

        validation = self.validator.validate_dimensions(values)
        if validation.status != "valid":
            raise InfeasibleStratumError("; ".join(validation.errors))
        generation_key = json.dumps(
            {
                "fixed": fixed,
                "distributions": distributions,
                "use_defaults": use_defaults,
                "generator": self.VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        persona_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:persona:{self.registry.VERSION}:{seed}:{generation_key}",
        )
        return PersonaBlueprint(
            persona_id=persona_id,
            schema_version=self.registry.VERSION,
            seed=seed,
            generator_version=self.VERSION,
            source="synthetic",
            dimensions=values,
            derived_traits=self._derive(values),
            provenance=provenance,
            validation=validation,
        )

    def generate_batch(
        self,
        size: int,
        seed: int,
        fixed: dict[str, Any] | None = None,
        distributions: dict[str, dict[Any, float]] | None = None,
    ) -> Iterator[PersonaBlueprint]:
        if size < 0:
            raise ValueError("size cannot be negative")
        for index in range(size):
            yield self.generate(
                seed * 10_000_000 + index,
                fixed,
                distributions,
            )

    def validate_stratum(
        self,
        fixed: dict[str, Any],
        distributions: dict[str, dict[Any, float]] | None = None,
    ) -> StratumFeasibility:
        try:
            self.generate(0, fixed, distributions)
        except (FixedFieldFeasibilityError, InfeasibleStratumError) as exc:
            return StratumFeasibility(
                feasible=False,
                fixed=fixed,
                errors=(str(exc),),
            )
        return StratumFeasibility(feasible=True, fixed=fixed)

    def _choose(
        self,
        rng: random.Random,
        name: str,
        candidates: tuple[Any, ...],
        current: dict[str, Any],
        fixed: dict[str, Any],
        distributions: dict[str, dict[Any, float]],
    ) -> tuple[Any, ProvenanceSource]:
        weights = distributions.get(name)
        if weights is not None:
            unknown = set(weights) - set(candidates)
            if unknown:
                raise InfeasibleStratumError(
                    f"Distribution {name} has unknown values: {sorted(unknown, key=str)}"
                )
            if any(
                not isinstance(weight, (int, float)) or weight < 0 for weight in weights.values()
            ):
                raise InfeasibleStratumError(
                    f"Distribution {name} weights must be non-negative numbers"
                )

        feasible: list[Any] = []
        feasible_weights: list[float] = []
        for candidate in candidates:
            proposed = {**current, name: candidate}
            if self.registry.constraint_errors(proposed, partial=True):
                continue
            if not self._allows_configured_dependencies(name, candidate, fixed, distributions):
                continue
            if not self._allows_future_constraints(proposed, fixed, distributions):
                continue
            feasible.append(candidate)
            feasible_weights.append(float(weights.get(candidate, 0)) if weights else 1.0)
        if not feasible or sum(feasible_weights) <= 0:
            raise InfeasibleStratumError(f"No feasible weighted value for {name}")
        selected = rng.choices(feasible, weights=feasible_weights, k=1)[0]
        source: ProvenanceSource = "weighted_distribution" if weights else "seeded_generator"
        return selected, source

    def _validate_fixed_assignments(self, fixed: dict[str, Any]) -> None:
        for name, value in fixed.items():
            spec = self.registry.dimensions[name]
            error = self.registry.validate_value(spec, value)
            if error:
                raise FixedFieldFeasibilityError(error)
            for parent, allowed in spec.depends_on.items():
                if parent in fixed and fixed[parent] not in allowed:
                    raise FixedFieldFeasibilityError(
                        f"Fixed dimension {name} is inactive for dependencies "
                        f"{spec.depends_on} under assignments {fixed}"
                    )
        constraint_errors = self.registry.constraint_errors(fixed, partial=True)
        if constraint_errors:
            raise FixedFieldFeasibilityError("; ".join(constraint_errors))

    def _allows_configured_dependencies(
        self,
        name: str,
        candidate: Any,
        fixed: dict[str, Any],
        distributions: dict[str, dict[Any, float]],
    ) -> bool:
        for child_name in set(fixed) | set(distributions):
            child = self.registry.dimensions[child_name]
            allowed = child.depends_on.get(name)
            if allowed is not None and candidate not in allowed:
                return False
        return True

    def _allows_future_constraints(
        self,
        proposed: dict[str, Any],
        fixed: dict[str, Any],
        distributions: dict[str, dict[Any, float]],
    ) -> bool:
        context = {**proposed, **fixed}
        for rule in self.registry.constraints:
            if any(name not in context for name in rule.when):
                continue
            if not all(context[name] in allowed for name, allowed in rule.when.items()):
                continue
            for target, allowed in rule.require.items():
                if target in fixed and fixed[target] not in allowed:
                    return False
                weights = distributions.get(target)
                if weights is not None and not any(
                    value in allowed and weight > 0 for value, weight in weights.items()
                ):
                    return False
            for target, forbidden in rule.forbid.items():
                if target in fixed and fixed[target] in forbidden:
                    return False
                weights = distributions.get(target)
                if weights is not None and not any(
                    value not in forbidden and weight > 0 for value, weight in weights.items()
                ):
                    return False
        return True

    @staticmethod
    def _derive(values: dict[str, Any]) -> dict[str, float | str | bool]:
        experience = {"NONE": 0.1, "LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.9}.get(
            str(values.get("rules_familiarity")), 0.5
        )
        patience = {"LOW": 0.2, "MEDIUM": 0.55, "HIGH": 0.85}.get(str(values.get("patience")), 0.5)
        reading = {"LOW": 0.2, "MEDIUM": 0.55, "HIGH": 0.85}.get(
            str(values.get("reading_tolerance")), 0.5
        )
        return {
            "onboarding_readiness": round((experience + patience + reading) / 3, 4),
            "needs_guided_help": experience < 0.4 or reading < 0.4,
            "play_archetype": values.get("player_style", "BALANCED"),
        }
