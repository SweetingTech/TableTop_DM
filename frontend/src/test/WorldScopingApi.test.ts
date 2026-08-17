import { describe, expect, it, vi } from "vitest";
import { demoPopulations } from "../core/demo/fixtures";
import {
  createActor,
  createEntity,
  createRun,
  createSnapshot,
  createTrialBranch,
  loadControlPlane,
} from "../features/control-plane/api";
import {
  activatePopulation,
  generatePopulation,
  loadPopulations,
  materializePopulation,
} from "../features/population-studio/api";

function ok(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function requestBody(call: [RequestInfo | URL, RequestInit?]): Record<string, unknown> {
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>;
}

describe("world-scoped frontend API contracts", () => {
  it("loads Control Plane actors through the selected world's authority view", async () => {
    vi.mocked(fetch).mockImplementation(async () => ok([]));
    const worldId = "11111111-1111-4111-8111-111111111111";

    await loadControlPlane(worldId);

    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toContain(
      `/api/v2/worlds/${worldId}/actors`,
    );
    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).not.toContain(
      `/api/v2/actors?world_id=${worldId}`,
    );
  });

  it("carries the active world through population generation and lifecycle writes", async () => {
    const population = demoPopulations[0];
    const worldId = "11111111-1111-4111-8111-111111111111";
    vi.mocked(fetch)
      .mockResolvedValueOnce(ok(population))
      .mockResolvedValueOnce(ok({ materialized: 24 }))
      .mockResolvedValueOnce(ok({ active: 8 }));

    await generatePopulation({ name: "Scoped pool", size: 100, seed: 17, world_id: worldId });
    await materializePopulation(population.population_id, 24, worldId);
    await activatePopulation(population.population_id, 8, worldId);

    const calls = vi.mocked(fetch).mock.calls;
    expect(requestBody(calls[0])).toMatchObject({ world_id: worldId });
    expect(requestBody(calls[1])).toEqual({ count: 24, world_id: worldId });
    expect(requestBody(calls[2])).toEqual({ count: 8, world_id: worldId });
  });

  it("filters population definitions to the selected world", async () => {
    const worldId = "11111111-1111-4111-8111-111111111111";
    const otherWorldId = "22222222-2222-4222-8222-222222222222";
    vi.mocked(fetch).mockResolvedValueOnce(ok([
      { ...demoPopulations[0], world_id: worldId },
      { ...demoPopulations[0], population_id: "other-pool", world_id: otherWorldId },
    ]));

    const result = await loadPopulations(worldId);

    expect(result.data.map((item) => item.world_id)).toEqual([worldId]);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      `/api/v2/populations/definitions?world_id=${worldId}`,
    );
  });

  it("scopes every Control Plane creation payload to the active world", async () => {
    const worldId = "11111111-1111-4111-8111-111111111111";
    const snapshotId = "33333333-3333-4333-8333-333333333333";
    vi.mocked(fetch).mockImplementation(async () => ok({}));

    await createActor(worldId, {
      display_name: "Harbor Guide",
      kind: "AGENT",
      roles: ["NPC"],
      capabilities: ["world.read", "action.propose"],
    });
    await createEntity(worldId, {
      name: "Quartermaster Ilyra",
      entity_type: "NPC",
      x: 3,
      y: 4,
    });
    await createRun(worldId, "LIVE", 101);
    await createSnapshot(worldId);
    await createTrialBranch(worldId, snapshotId, 202);

    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.map(([url]) => url)).toEqual([
      "/api/v2/actors",
      `/api/v2/worlds/${worldId}/entities`,
      "/api/v2/runs",
      `/api/v2/worlds/${worldId}/snapshots`,
      `/api/v2/snapshots/${snapshotId}/branches`,
    ]);
    expect(requestBody(calls[0])).toMatchObject({ world_id: worldId, roles: ["NPC"] });
    expect(requestBody(calls[1])).toMatchObject({
      controller_actor_id: null,
      public_state: { x: 3, y: 4 },
    });
    expect(requestBody(calls[2])).toEqual({ world_id: worldId, kind: "LIVE", seed: 101 });
    expect(requestBody(calls[4])).toEqual({ world_id: worldId, seed: 202 });
  });
});
