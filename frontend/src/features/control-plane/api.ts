import { apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { ActorSummary, BranchSummary, EntitySummary, RunSummary, SnapshotSummary, Sourced, WorldSummary } from "../../core/api/types";
import { demoActors, demoBranches, demoEntities, demoRuns, demoSnapshots, demoWorlds } from "../../core/demo/fixtures";

export type ControlPlaneData = {
  worlds: WorldSummary[];
  actors: ActorSummary[];
  entities: EntitySummary[];
  runs: RunSummary[];
  snapshots: SnapshotSummary[];
  branches: BranchSummary[];
};

export async function loadControlPlane(worldId: string): Promise<Sourced<ControlPlaneData>> {
  return withDemoFallback(
    async () => {
      const query = `world_id=${encodeURIComponent(worldId)}`;
      const [worlds, actors, entities, runs, snapshots, branches] = await Promise.all([
        apiRequest<WorldSummary[] | { items?: WorldSummary[] }>("/worlds"),
        apiRequest<ActorSummary[] | { items?: ActorSummary[] }>(`/worlds/${encodeURIComponent(worldId)}/actors`),
        apiRequest<EntitySummary[] | { items?: EntitySummary[] }>(`/worlds/${worldId}/entities`),
        apiRequest<RunSummary[] | { items?: RunSummary[] }>(`/runs?${query}`),
        apiRequest<SnapshotSummary[] | { items?: SnapshotSummary[] }>(`/snapshots?${query}`),
        apiRequest<BranchSummary[] | { items?: BranchSummary[] }>(`/branches?${query}`),
      ]);
      return { worlds: unpackItems(worlds), actors: unpackItems(actors), entities: unpackItems(entities), runs: unpackItems(runs), snapshots: unpackItems(snapshots), branches: unpackItems(branches) };
    },
    () => ({ worlds: demoWorlds, actors: demoActors, entities: demoEntities, runs: demoRuns, snapshots: demoSnapshots, branches: demoBranches }),
    "Control plane",
  );
}

export async function createWorld(name: string): Promise<Sourced<WorldSummary>> {
  return withDemoFallback(
    () => apiRequest<WorldSummary>("/worlds", { method: "POST", body: JSON.stringify({ name }) }),
    () => ({ world_id: `demo-world-${name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-")}`, name: name.trim(), status: "IDLE", updated_at: "2026-08-17T15:00:00Z" }),
    "World creation",
  );
}

export async function createActor(
  worldId: string,
  input: Pick<ActorSummary, "display_name" | "kind" | "roles" | "capabilities">,
): Promise<Sourced<ActorSummary>> {
  return withDemoFallback(
    () => apiRequest<ActorSummary>("/actors", {
      method: "POST",
      body: JSON.stringify({ ...input, world_id: worldId }),
    }),
    () => ({
      actor_id: `demo-actor-${input.display_name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      world_id: worldId,
      ...input,
    }),
    "Actor creation",
  );
}

export async function createEntity(
  worldId: string,
  input: {
    name: string;
    entity_type: string;
    controller_actor_id?: string;
    x: number;
    y: number;
  },
): Promise<Sourced<EntitySummary>> {
  return withDemoFallback(
    () => apiRequest<EntitySummary>(`/worlds/${encodeURIComponent(worldId)}/entities`, {
      method: "POST",
      body: JSON.stringify({
        name: input.name,
        entity_type: input.entity_type,
        controller_actor_id: input.controller_actor_id || null,
        public_state: { x: input.x, y: input.y, hp: 10, max_hp: 10 },
      }),
    }),
    () => ({
      entity_id: `demo-entity-${input.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      world_id: worldId,
      name: input.name,
      entity_type: input.entity_type,
      controller_actor_id: input.controller_actor_id || null,
      public_state: { x: input.x, y: input.y, hp: 10, max_hp: 10 },
      location: `(${input.x}, ${input.y})`,
      health: 10,
      max_health: 10,
      status: "ACTIVE",
    }),
    "Entity creation",
  );
}

export async function createRun(
  worldId: string,
  kind: RunSummary["kind"],
  seed: number,
): Promise<Sourced<RunSummary>> {
  return withDemoFallback(
    () => apiRequest<RunSummary>("/runs", {
      method: "POST",
      body: JSON.stringify({ world_id: worldId, kind, seed }),
    }),
    () => ({
      run_id: `demo-run-${kind.toLowerCase()}-${seed}`,
      world_id: worldId,
      name: `${kind.toLowerCase()} run`,
      kind,
      status: "RUNNING",
    }),
    "Run creation",
  );
}

export async function createSnapshot(worldId: string): Promise<Sourced<Record<string, unknown>>> {
  return withDemoFallback(
    () => apiRequest<Record<string, unknown>>(`/worlds/${encodeURIComponent(worldId)}/snapshots`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
    () => ({ snapshot_id: `demo-snapshot-${worldId}`, world_id: worldId }),
    "Snapshot creation",
  );
}

export async function createTrialBranch(
  worldId: string,
  snapshotId: string,
  seed: number,
): Promise<Sourced<Record<string, unknown>>> {
  return withDemoFallback(
    () => apiRequest<Record<string, unknown>>(`/snapshots/${encodeURIComponent(snapshotId)}/branches`, {
      method: "POST",
      body: JSON.stringify({ world_id: worldId, seed }),
    }),
    () => ({
      branch_id: `demo-branch-${seed}`,
      branch_kind: "TRIAL",
      world_id: worldId,
      base_snapshot_id: snapshotId,
    }),
    "Trial branch creation",
  );
}
