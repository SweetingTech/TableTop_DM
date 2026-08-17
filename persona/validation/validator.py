from __future__ import annotations

from typing import Any

from persona.models import PersonaBlueprint, PersonaValidation
from persona.registry import PersonaSchemaRegistry


class PersonaValidator:
    RULESET_VERSION = "constraints-0.2.0"

    def __init__(self, registry: PersonaSchemaRegistry) -> None:
        self.registry = registry

    def validate_dimensions(
        self,
        dimensions: dict[str, Any],
        *,
        require_complete: bool = True,
    ) -> PersonaValidation:
        errors: list[str] = []
        unknown = set(dimensions) - set(self.registry.dimensions)
        if unknown:
            errors.append(f"Unknown dimensions: {sorted(unknown)}")

        active: list[str] = []
        known_values: dict[str, Any] = {}
        for spec in self.registry.ordered_dimensions():
            enabled = self.registry.is_enabled(spec, known_values)
            if not enabled:
                if spec.name in dimensions:
                    errors.append(f"{spec.name} is inactive for its dependency assignments")
                continue
            active.append(spec.name)
            if spec.name not in dimensions:
                if require_complete:
                    errors.append(f"Missing active dimension: {spec.name}")
                continue
            value = dimensions[spec.name]
            value_error = self.registry.validate_value(spec, value)
            if value_error:
                errors.append(value_error)
            else:
                known_values[spec.name] = value

        errors.extend(self.registry.constraint_errors(dimensions, partial=not require_complete))
        return PersonaValidation(
            status="invalid" if errors else "valid",
            ruleset_version=self.RULESET_VERSION,
            errors=tuple(errors),
            active_dimensions=tuple(active),
        )

    def validate_blueprint(self, blueprint: PersonaBlueprint) -> PersonaValidation:
        validation = self.validate_dimensions(blueprint.dimensions)
        errors = list(validation.errors)
        missing_provenance = set(blueprint.dimensions) - set(blueprint.provenance)
        if missing_provenance:
            errors.append(f"Missing provenance for dimensions: {sorted(missing_provenance)}")
        return validation.model_copy(
            update={
                "status": "invalid" if errors else "valid",
                "errors": tuple(errors),
            }
        )
