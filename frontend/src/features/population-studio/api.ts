import { apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { CohortMember, PopulationDefinition, Sourced } from "../../core/api/types";
import { demoCohort, demoPopulations } from "../../core/demo/fixtures";

export async function loadPopulations(worldId: string): Promise<Sourced<PopulationDefinition[]>> {
  return withDemoFallback(
    async () => {
      const items = unpackItems(await apiRequest<PopulationDefinition[] | { items?: PopulationDefinition[] }>(`/populations/definitions?world_id=${encodeURIComponent(worldId)}`));
      return items.filter((item) => item.world_id === worldId);
    },
    () => demoPopulations.filter((item) => item.world_id === worldId),
    "Population definitions",
  );
}

export async function generatePopulation(input: { name: string; size: number; seed: number; world_id: string }): Promise<Sourced<PopulationDefinition>> {
  return withDemoFallback(
    () => apiRequest<PopulationDefinition>("/populations/generate", { method: "POST", body: JSON.stringify(input) }),
    () => ({ population_id: `pop-demo-${input.seed}`, world_id: input.world_id, name: input.name, size: input.size, status: "READY", schema_version: "2.0.0", seed: input.seed, materialized: 0, active: 0, dimensions: { risk_tolerance: { LOW: Math.round(input.size * 0.28), MEDIUM: Math.round(input.size * 0.55), HIGH: input.size - Math.round(input.size * 0.28) - Math.round(input.size * 0.55) } } }),
    "Population generation",
  );
}

export async function samplePopulation(populationId: string, perCell: number): Promise<Sourced<CohortMember[]>> {
  return withDemoFallback(
    async () => unpackItems(await apiRequest<CohortMember[] | { items?: CohortMember[] }>(`/populations/${populationId}/sample`, { method: "POST", body: JSON.stringify({ strata: ["occupation_sector", "risk_tolerance"], per_cell: perCell, seed: 202 }) })),
    () => demoCohort(Math.min(24, Math.max(1, perCell * 4))),
    "Population sampling",
  );
}

export async function materializePopulation(populationId: string, count: number, worldId: string): Promise<Sourced<{ materialized: number }>> {
  return withDemoFallback(
    () => apiRequest<{ materialized: number }>(`/populations/${populationId}/materialize`, { method: "POST", body: JSON.stringify({ count, world_id: worldId }) }),
    () => ({ materialized: count }),
    "Population materialization",
  );
}

export async function activatePopulation(populationId: string, count: number, worldId: string): Promise<Sourced<{ active: number }>> {
  return withDemoFallback(
    () => apiRequest<{ active: number }>(`/populations/${populationId}/activate`, { method: "POST", body: JSON.stringify({ count, world_id: worldId }) }),
    () => ({ active: count }),
    "Population activation",
  );
}
