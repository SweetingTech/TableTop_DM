from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from persona.generation import PersonaGenerator
from persona.models import DimensionSpec
from persona.registry import PersonaSchemaRegistry
from population.models import (
    CohortDefinition,
    CohortFeasibilityReport,
    DistributionToleranceReport,
    FeasibilityCell,
    PopulationDefinition,
)


class PopulationStore:
    """Immutable Parquet persona pools queried and sampled inside DuckDB."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.registry = PersonaSchemaRegistry.load_default()
        self.generator = PersonaGenerator(self.registry)

    def generate(
        self,
        size: int,
        seed: int,
        *,
        batch_size: int = 10_000,
    ) -> Path:
        return self.generate_definition(
            PopulationDefinition(
                population_key=self.path.stem,
                version="1.0.0",
                size=size,
                seed=seed,
            ),
            batch_size=batch_size,
        )

    def generate_definition(
        self,
        definition: PopulationDefinition,
        *,
        batch_size: int = 10_000,
    ) -> Path:
        if batch_size < 1 or batch_size > 100_000:
            raise ValueError("batch_size must be between 1 and 100000")
        feasibility = self.generator.validate_stratum(definition.fixed, definition.distributions)
        if not feasibility.feasible:
            raise ValueError("; ".join(feasibility.errors))

        schema = self._arrow_schema()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        writer: pq.ParquetWriter | None = None
        try:
            writer = pq.ParquetWriter(
                temporary,
                schema,
                compression="zstd",
                version="2.6",
            )
            for start in range(0, definition.size, batch_size):
                stop = min(start + batch_size, definition.size)
                rows = [
                    self._persona_row(
                        self.generator.generate(
                            definition.seed * 10_000_000 + index,
                            definition.fixed,
                            definition.distributions,
                        )
                    )
                    for index in range(start, stop)
                ]
                writer.write_table(
                    pa.Table.from_pylist(rows, schema=schema),
                    row_group_size=batch_size,
                )
            writer.close()
            writer = None
            os.replace(temporary, self.path)
        except Exception:
            if writer is not None:
                writer.close()
            if temporary.exists():
                temporary.unlink()
            raise
        return self.path

    def count(self, filters: dict[str, Any] | None = None) -> int:
        where, filter_parameters = self._filter_clause(filters or {})
        query = f"SELECT count(*) FROM read_parquet(?) {where}"
        with duckdb.connect(":memory:") as connection:
            row = connection.execute(query, [str(self.path), *filter_parameters]).fetchone()
        return int(row[0]) if row is not None else 0

    def get(self, persona_id: Any) -> dict[str, Any]:
        rows = self._fetch_dicts(
            "SELECT * FROM read_parquet(?) WHERE persona_id = ? LIMIT 1",
            [str(self.path), str(persona_id)],
        )
        if not rows:
            raise KeyError(persona_id)
        return rows[0]

    def sample_stratified(
        self,
        strata: tuple[str, ...],
        per_cell: int,
        seed: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if per_cell < 1:
            raise ValueError("per_cell must be positive")
        self._validate_dimensions(strata, "strata")
        where, filter_parameters = self._filter_clause(filters or {})
        partition = ", ".join(self._quote(name) for name in strata) or "1"
        ordering = ", ".join(self._quote(name) for name in strata)
        final_order = f"{ordering}, _sample_rank" if ordering else "_sample_rank"
        query = f"""
            WITH eligible AS (
              SELECT * FROM read_parquet(?) {where}
            ), ranked AS (
              SELECT *, row_number() OVER (
                PARTITION BY {partition}
                ORDER BY hash(persona_id || ':' || CAST(? AS VARCHAR)), persona_id
              ) AS _sample_rank
              FROM eligible
            )
            SELECT * EXCLUDE (_sample_rank)
            FROM ranked
            WHERE _sample_rank <= ?
            ORDER BY {final_order}
        """
        return self._fetch_dicts(
            query,
            [str(self.path), *filter_parameters, seed, per_cell],
        )

    def sample_weighted(
        self,
        size: int,
        seed: int,
        dimension: str,
        weights: dict[Any, float],
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if size < 1:
            raise ValueError("size must be positive")
        self._validate_dimensions((dimension,), "weight dimension")
        spec = self.registry.dimensions[dimension]
        self._validate_weights(spec, weights)
        eligible_filters = self._weighted_filters(dimension, weights, filters or {})
        available = self.count(eligible_filters)
        if available < size:
            raise ValueError(f"Weighted sample needs {size}, found {available}")
        where, filter_parameters = self._filter_clause(filters or {})
        cases: list[str] = []
        case_parameters: list[Any] = []
        for value in sorted(weights, key=str):
            cases.append("WHEN ? THEN ?")
            case_parameters.extend((value, float(weights[value])))
        weight_expression = f"CASE {self._quote(dimension)} {' '.join(cases)} ELSE 0.0 END"
        query = f"""
            WITH weighted AS (
              SELECT *, {weight_expression} AS _weight
              FROM read_parquet(?) {where}
            ), ranked AS (
              SELECT *,
                -ln(((hash(persona_id || ':' || CAST(? AS VARCHAR)) % 1000000)
                    + 1)::DOUBLE / 1000001.0) / _weight AS _sample_key
              FROM weighted
              WHERE _weight > 0
            )
            SELECT * EXCLUDE (_weight, _sample_key)
            FROM ranked
            ORDER BY _sample_key, persona_id
            LIMIT ?
        """
        return self._fetch_dicts(
            query,
            [
                *case_parameters,
                str(self.path),
                *filter_parameters,
                seed,
                size,
            ],
        )

    def sample_cohort(self, definition: CohortDefinition) -> list[dict[str, Any]]:
        feasibility = self.cohort_feasibility(definition)
        if not feasibility.feasible:
            raise ValueError("; ".join(feasibility.errors) or "Cohort is infeasible")
        if definition.sampling_mode == "WEIGHTED":
            if definition.weight_dimension is None or not definition.weights:
                raise ValueError("Weighted cohorts require a dimension and weights")
            return self.sample_weighted(
                definition.sample_size or definition.per_cell,
                definition.seed,
                definition.weight_dimension,
                definition.weights,
                definition.filters,
            )
        return self.sample_stratified(
            definition.strata,
            definition.per_cell,
            definition.seed,
            definition.filters,
        )

    def cohort_feasibility(self, definition: CohortDefinition) -> CohortFeasibilityReport:
        invalid = set(definition.strata) - set(self.registry.dimensions)
        if definition.weight_dimension is not None:
            invalid |= {definition.weight_dimension} - set(self.registry.dimensions)
        invalid |= set(definition.filters) - set(self.registry.dimensions)
        if invalid:
            return CohortFeasibilityReport(
                cohort_key=definition.cohort_key,
                feasible=False,
                total_available=0,
                cells=(),
                errors=(f"Unknown cohort dimensions: {sorted(invalid)}",),
            )
        total = self.count(definition.filters)
        errors: tuple[str, ...]
        if definition.sampling_mode == "WEIGHTED":
            required = definition.sample_size or definition.per_cell
            if definition.weight_dimension is None or not definition.weights:
                return CohortFeasibilityReport(
                    cohort_key=definition.cohort_key,
                    feasible=False,
                    total_available=total,
                    cells=(),
                    errors=("Weighted cohorts require a dimension and weights",),
                )
            try:
                spec = self.registry.dimensions[definition.weight_dimension]
                self._validate_weights(spec, definition.weights)
                eligible_filters = self._weighted_filters(
                    definition.weight_dimension,
                    definition.weights,
                    definition.filters,
                )
                eligible = self.count(eligible_filters)
            except ValueError as exc:
                return CohortFeasibilityReport(
                    cohort_key=definition.cohort_key,
                    feasible=False,
                    total_available=total,
                    cells=(),
                    errors=(str(exc),),
                )
            errors = (
                ()
                if eligible >= required
                else (f"Weighted sample needs {required}, found {eligible}",)
            )
            return CohortFeasibilityReport(
                cohort_key=definition.cohort_key,
                feasible=not errors,
                total_available=total,
                cells=(
                    FeasibilityCell(
                        values={},
                        available=eligible,
                        required=required,
                        feasible=not errors,
                    ),
                ),
                errors=errors,
            )

        counts = self._strata_counts(definition.strata, definition.filters)
        required_cells = self._required_cells(definition)
        cells: list[FeasibilityCell] = []
        for cell in required_cells:
            key = tuple(cell[name] for name in definition.strata)
            available = counts.get(key, 0)
            cells.append(
                FeasibilityCell(
                    values=cell,
                    available=available,
                    required=definition.per_cell,
                    feasible=available >= definition.per_cell,
                )
            )
        errors = tuple(
            f"Cell {cell.values} needs {cell.required}, found {cell.available}"
            for cell in cells
            if not cell.feasible
        )
        return CohortFeasibilityReport(
            cohort_key=definition.cohort_key,
            feasible=not errors,
            total_available=total,
            cells=tuple(cells),
            errors=errors,
        )

    def distribution_tolerance(
        self,
        dimension: str,
        expected_weights: dict[Any, float],
        *,
        tolerance: float,
        filters: dict[str, Any] | None = None,
    ) -> DistributionToleranceReport:
        if not 0 <= tolerance <= 1:
            raise ValueError("tolerance must be between 0 and 1")
        self._validate_dimensions((dimension,), "distribution dimension")
        spec = self.registry.dimensions[dimension]
        self._validate_weights(spec, expected_weights)
        where, parameters = self._filter_clause(filters or {})
        query = f"""
            SELECT {self._quote(dimension)}, count(*)
            FROM read_parquet(?) {where}
            GROUP BY {self._quote(dimension)}
        """
        with duckdb.connect(":memory:") as connection:
            rows = connection.execute(query, [str(self.path), *parameters]).fetchall()
        counts = {str(value): int(count) for value, count in rows if value is not None}
        population_count = sum(counts.values())
        total_weight = sum(float(weight) for weight in expected_weights.values())
        expected = {
            str(value): round(float(weight) / total_weight, 8)
            for value, weight in sorted(expected_weights.items(), key=lambda item: str(item[0]))
        }
        observed = {
            value: round(counts.get(value, 0) / population_count, 8) if population_count else 0.0
            for value in expected
        }
        deviation = {value: round(abs(observed[value] - expected[value]), 8) for value in expected}
        return DistributionToleranceReport(
            dimension=dimension,
            population_count=population_count,
            expected=expected,
            observed=observed,
            absolute_deviation=deviation,
            tolerance=tolerance,
            within_tolerance=all(value <= tolerance for value in deviation.values()),
        )

    def _required_cells(self, definition: CohortDefinition) -> list[dict[str, Any]]:
        if not definition.strata:
            return [{}]
        if definition.required_cells:
            explicit_cells = [dict(cell) for cell in definition.required_cells]
            for cell in explicit_cells:
                if set(cell) != set(definition.strata):
                    raise ValueError("Required cells must assign every stratum")
            return explicit_cells

        choices: list[tuple[Any, ...]] = []
        for name in definition.strata:
            if name in definition.filters:
                raw = definition.filters[name]
                values = raw if isinstance(raw, (list, tuple, set)) else (raw,)
                choices.append(tuple(sorted(values, key=str)))
            else:
                spec = self.registry.dimensions[name]
                if spec.kind == "enum":
                    choices.append(spec.values)
                elif spec.kind == "boolean":
                    choices.append((False, True))
                else:
                    raise ValueError(f"Numeric stratum {name} requires explicit required_cells")
        if self._product_size(choices) > 10_000:
            raise ValueError("Derived cohort cell count exceeds 10000")
        cells: list[dict[str, Any]] = []
        singleton_filters = {
            name: value
            for name, raw in definition.filters.items()
            if not isinstance(raw, (list, tuple, set))
            for value in (raw,)
        }
        for combination in itertools.product(*choices):
            cell = dict(zip(definition.strata, combination, strict=True))
            fixed = {**singleton_filters, **cell}
            if self.generator.validate_stratum(fixed).feasible:
                cells.append(cell)
        return cells

    def _strata_counts(
        self, strata: tuple[str, ...], filters: dict[str, Any]
    ) -> dict[tuple[Any, ...], int]:
        if not strata:
            return {(): self.count(filters)}
        where, parameters = self._filter_clause(filters)
        columns = ", ".join(self._quote(name) for name in strata)
        query = f"""
            SELECT {columns}, count(*)
            FROM read_parquet(?) {where}
            GROUP BY {columns}
        """
        with duckdb.connect(":memory:") as connection:
            rows = connection.execute(query, [str(self.path), *parameters]).fetchall()
        return {tuple(row[:-1]): int(row[-1]) for row in rows}

    def _filter_clause(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self._validate_dimensions(tuple(filters), "filters")
        conditions: list[str] = []
        parameters: list[Any] = []
        for name in sorted(filters):
            raw = filters[name]
            values = raw if isinstance(raw, (list, tuple, set)) else (raw,)
            ordered_values = tuple(sorted(values, key=str))
            if not ordered_values:
                conditions.append("false")
                continue
            placeholders = ",".join("?" for _ in ordered_values)
            conditions.append(f"{self._quote(name)} IN ({placeholders})")
            parameters.extend(ordered_values)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return where, parameters

    @staticmethod
    def _weighted_filters(
        dimension: str,
        weights: dict[Any, float],
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        eligible_values = {value for value, weight in weights.items() if float(weight) > 0}
        combined = dict(filters)
        if dimension in combined:
            raw = combined[dimension]
            current = set(raw if isinstance(raw, (list, tuple, set)) else (raw,))
            eligible_values &= current
        combined[dimension] = tuple(sorted(eligible_values, key=str))
        return combined

    def _validate_dimensions(self, dimensions: tuple[str, ...], label: str) -> None:
        invalid = set(dimensions) - set(self.registry.dimensions)
        if invalid:
            raise ValueError(f"Unknown {label}: {sorted(invalid)}")

    def _validate_weights(self, spec: DimensionSpec, weights: dict[Any, float]) -> None:
        candidates: set[Any]
        if spec.kind == "enum":
            candidates = set(spec.values)
        elif spec.kind == "boolean":
            candidates = {False, True}
        else:
            raise ValueError("Weighted sampling requires an enum or boolean dimension")
        unknown = set(weights) - candidates
        if unknown:
            raise ValueError(f"Unknown weights for {spec.name}: {sorted(unknown, key=str)}")
        if not weights or any(
            not isinstance(weight, (int, float)) or weight < 0 for weight in weights.values()
        ):
            raise ValueError("Weights must be non-negative numbers")
        if sum(float(weight) for weight in weights.values()) <= 0:
            raise ValueError("At least one weight must be positive")

    def _arrow_schema(self) -> pa.Schema:
        fields = [
            pa.field("persona_id", pa.string(), nullable=False),
            pa.field("schema_version", pa.string(), nullable=False),
            pa.field("seed", pa.int64(), nullable=False),
            pa.field("generator_version", pa.string(), nullable=False),
            pa.field("dimensions_json", pa.string(), nullable=False),
        ]
        for spec in self.registry.ordered_dimensions():
            arrow_type: pa.DataType
            if spec.kind == "boolean":
                arrow_type = pa.bool_()
            elif spec.kind == "integer":
                arrow_type = pa.int64()
            elif spec.kind == "number":
                arrow_type = pa.float64()
            else:
                arrow_type = pa.string()
            fields.append(pa.field(spec.name, arrow_type, nullable=True))
        return pa.schema(fields)

    @staticmethod
    def _persona_row(persona: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "persona_id": str(persona.persona_id),
            "schema_version": persona.schema_version,
            "seed": persona.seed,
            "generator_version": persona.generator_version,
            "dimensions_json": json.dumps(persona.dimensions, sort_keys=True),
        }
        row.update(persona.dimensions)
        return row

    @staticmethod
    def _fetch_dicts(query: str, parameters: list[Any]) -> list[dict[str, Any]]:
        with duckdb.connect(":memory:") as connection:
            cursor = connection.execute(query, parameters)
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    @staticmethod
    def _quote(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    @staticmethod
    def _product_size(choices: list[tuple[Any, ...]]) -> int:
        size = 1
        for choice in choices:
            size *= len(choice)
        return size
