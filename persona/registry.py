from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from persona.models import DimensionSpec, DomainPackMetadata, PersonaConstraint


class PersonaSchemaRegistry:
    VERSION = "2.0.0"

    def __init__(
        self,
        dimensions: dict[str, DimensionSpec],
        constraints: tuple[PersonaConstraint, ...] = (),
        domain_packs: dict[str, DomainPackMetadata] | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.constraints = constraints
        self.domain_packs = domain_packs or {}

    @classmethod
    def load_default(cls) -> PersonaSchemaRegistry:
        root = Path(__file__).parent / "schema"
        dimensions: dict[str, DimensionSpec] = {}
        constraints: list[PersonaConstraint] = []
        domain_packs: dict[str, DomainPackMetadata] = {}
        for path in sorted(root.rglob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            pack_payload = payload.get(
                "pack",
                {
                    "pack_id": path.parent.name,
                    "version": "1.0.0",
                    "description": f"{path.parent.name.title()} persona dimensions",
                },
            )
            pack = DomainPackMetadata.model_validate(pack_payload)
            if pack.pack_id in domain_packs and domain_packs[pack.pack_id] != pack:
                raise ValueError(f"Conflicting domain pack metadata: {pack.pack_id}")
            domain_packs[pack.pack_id] = pack
            for raw in payload.get("dimensions", []):
                raw = dict(raw)
                raw.setdefault("domain_pack", pack.pack_id)
                spec = DimensionSpec.model_validate(raw)
                if spec.name in dimensions:
                    raise ValueError(f"Duplicate persona dimension {spec.name}")
                dimensions[spec.name] = spec
            constraints.extend(
                PersonaConstraint.model_validate(raw) for raw in payload.get("constraints", [])
            )
        registry = cls(dimensions, tuple(constraints), domain_packs)
        registry.validate_graph()
        return registry

    def validate_graph(self) -> None:
        for name, spec in self.dimensions.items():
            missing = set(spec.depends_on) - set(self.dimensions)
            if missing:
                raise ValueError(f"{name} depends on unknown dimensions: {sorted(missing)}")
            if spec.default is None:
                raise ValueError(f"{name} must declare a default")
            default_error = self.validate_value(spec, spec.default)
            if default_error:
                raise ValueError(f"Invalid default: {default_error}")
            for parent, allowed in spec.depends_on.items():
                parent_spec = self.dimensions[parent]
                invalid = [
                    value
                    for value in allowed
                    if self.validate_value(parent_spec, value) is not None
                ]
                if invalid:
                    raise ValueError(f"{name} dependency {parent} has invalid values: {invalid}")
        rule_ids: set[str] = set()
        for rule in self.constraints:
            if rule.rule_id in rule_ids:
                raise ValueError(f"Duplicate persona constraint {rule.rule_id}")
            rule_ids.add(rule.rule_id)
            referenced = set(rule.when) | set(rule.require) | set(rule.forbid)
            missing = referenced - set(self.dimensions)
            if missing:
                raise ValueError(
                    f"Constraint {rule.rule_id} references unknown dimensions: {sorted(missing)}"
                )
            clauses = list(rule.when.items())
            clauses.extend(rule.require.items())
            clauses.extend(rule.forbid.items())
            for dimension, allowed in clauses:
                invalid = [
                    value
                    for value in allowed
                    if self.validate_value(self.dimensions[dimension], value) is not None
                ]
                if invalid:
                    raise ValueError(
                        f"Constraint {rule.rule_id} has invalid {dimension} values: {invalid}"
                    )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError(f"Persona dependency cycle includes {name}")
            if name in visited:
                return
            visiting.add(name)
            for dependency in self.generation_dependencies(name):
                visit(dependency)
            visiting.remove(name)
            visited.add(name)

        for name in self.dimensions:
            visit(name)

    def ordered_dimensions(self) -> list[DimensionSpec]:
        ordered: list[DimensionSpec] = []
        remaining = dict(self.dimensions)
        emitted: set[str] = set()
        while remaining:
            ready = sorted(
                name for name in remaining if self.generation_dependencies(name).issubset(emitted)
            )
            if not ready:
                raise ValueError("Persona dependency graph cannot be ordered")
            for name in ready:
                ordered.append(remaining.pop(name))
                emitted.add(name)
        return ordered

    def generation_dependencies(self, name: str) -> set[str]:
        dependencies = set(self.dimensions[name].depends_on)
        for rule in self.constraints:
            if name in rule.require or name in rule.forbid:
                dependencies.update(rule.when)
        dependencies.discard(name)
        return dependencies

    def validate_value(self, spec: DimensionSpec, value: Any) -> str | None:
        if spec.kind == "enum" and value not in spec.values:
            return f"{spec.name} must be one of {list(spec.values)}"
        if spec.kind == "boolean" and not isinstance(value, bool):
            return f"{spec.name} must be boolean"
        if spec.kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"{spec.name} must be an integer"
        if spec.kind == "number" and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            return f"{spec.name} must be numeric"
        if spec.kind in {"integer", "number"}:
            if spec.minimum is not None and value < spec.minimum:
                return f"{spec.name} must be >= {spec.minimum}"
            if spec.maximum is not None and value > spec.maximum:
                return f"{spec.name} must be <= {spec.maximum}"
        return None

    @staticmethod
    def is_enabled(spec: DimensionSpec, values: dict[str, Any]) -> bool:
        return all(values.get(parent) in allowed for parent, allowed in spec.depends_on.items())

    def defaults(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in self.ordered_dimensions():
            if self.is_enabled(spec, values):
                values[spec.name] = spec.default
        return values

    def constraint_errors(
        self, values: dict[str, Any], *, partial: bool = False
    ) -> tuple[str, ...]:
        errors: list[str] = []
        for rule in self.constraints:
            if any(name not in values for name in rule.when):
                continue
            if not all(values[name] in allowed for name, allowed in rule.when.items()):
                continue
            violations: list[str] = []
            for name, allowed in rule.require.items():
                if name not in values:
                    if not partial:
                        violations.append(f"{name} is required")
                elif values[name] not in allowed:
                    violations.append(f"{name} must be one of {list(allowed)}")
            for name, forbidden in rule.forbid.items():
                if name in values and values[name] in forbidden:
                    violations.append(f"{name} cannot be {values[name]}")
            if violations:
                detail = rule.message or "; ".join(violations)
                errors.append(f"{rule.rule_id}: {detail}")
        return tuple(errors)
