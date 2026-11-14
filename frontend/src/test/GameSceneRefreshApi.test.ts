import { afterEach, describe, expect, it, vi } from "vitest";
import { demoGameState } from "../core/demo/fixtures";
import type { PerceivedScene } from "../core/api/types";
import { loadGameState, proposeCommand } from "../features/game-console/api";
import { SCENE_REFRESH_POLL_MS, SCENE_REFRESH_TIMEOUT_MS, waitForScene } from "../features/game-console/sceneRefresh";

const cursor = { world_id: "world", branch_id: "branch", observer_entity_id: "hero", event_id: "event", projection_version: 2 };
function scene(ready: boolean, version = 2, observed = ready): PerceivedScene {
  return { world_id: "world", branch_id: "branch", observer_entity_id: "hero", projection_version: version,
    perceived_entities: [], recent_observations: [], visible_zones: [], available_viewpoints: ["hero"],
    refresh: { event_id: "event", ready, observed } };
}
function ok(payload: unknown, status = 200) { return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }); }
function metadata(input: RequestInfo | URL): Response | null {
  const url = String(input);
  if (url.includes("/viewpoints")) return ok({ items: [{ entity_id: "hero", name: "Nyra", entity_type: "PLAYER_CHARACTER", can_act: true }] });
  if (url.includes("/runs?")) return ok([]);
  if (url.includes("/branches?")) return ok([{ branch_id: "branch", world_id: "world", kind: "CANONICAL", name: "canonical", status: "ACTIVE" }]);
  return null;
}
afterEach(() => vi.useRealTimers());

describe("scene projection barrier", () => {
  it("waits for both the accepted canonical version and projected observation", async () => {
    vi.useFakeTimers();
    const read = vi.fn().mockResolvedValueOnce(scene(true, 1)).mockResolvedValueOnce(scene(false)).mockResolvedValue(scene(true));
    const result = waitForScene(read, cursor);
    await vi.advanceTimersByTimeAsync(SCENE_REFRESH_POLL_MS * 2);
    expect((await result).projection_version).toBe(2); expect(read).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("bounds observation lag and never returns a stale scene as success", async () => {
    vi.useFakeTimers();
    const read = vi.fn().mockResolvedValue(scene(false));
    const result = expect(waitForScene(read, cursor)).rejects.toThrow(/still updating/);
    await vi.advanceTimersByTimeAsync(SCENE_REFRESH_TIMEOUT_MS);
    await result; expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels old-scope polling without further reads", async () => {
    vi.useFakeTimers(); const controller = new AbortController();
    const read = vi.fn().mockResolvedValue(scene(false));
    const result = expect(waitForScene(read, cursor, controller.signal)).rejects.toThrow(/cancelled/);
    await vi.advanceTimersByTimeAsync(0); controller.abort(); await result;
    await vi.advanceTimersByTimeAsync(SCENE_REFRESH_TIMEOUT_MS);
    expect(read).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });

  it("finishes an unperceived action without adding an observation", async () => {
    const result = await waitForScene(async () => scene(true, 2, false), cursor);
    expect(result.recent_observations).toEqual([]); expect(result.refresh?.observed).toBe(false);
  });

  it("rejects mismatched world/body and receipt responses", async () => {
    await expect(waitForScene(async () => ({ ...scene(true), observer_entity_id: "someone-else" }), cursor)).rejects.toThrow(/selected world and character/);
    await expect(waitForScene(async () => ({ ...scene(true), refresh: { event_id: "other", ready: true, observed: true } }), cursor)).rejects.toThrow(/acknowledge/);
  });
});

describe("live scene API", () => {
  it("uses the command cursor and retains observation source identity", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => metadata(input) ?? ok({ ...scene(true), recent_observations: [{ observation_id: "observation", source_event_id: "event", event_type: "tabletop.spatial.move", summary: "A footstep", observed_at: "2026-11-13T00:00:00Z", confidence: 1, immediate_source_entity_id: null }] }));
    const result = await loadGameState("world", "hero", cursor);
    expect(vi.mocked(fetch).mock.calls.map(([url]) => url)).toContain("/api/v2/worlds/world/branches/branch/entities/hero/scene?after_event_id=event");
    expect(result.data.events[0]).toMatchObject({ event_id: "observation", source_event_id: "event" });
  });

  it("does not fabricate demo success for a failed live write or post-acceptance read", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => metadata(input) ?? ok({ error: "unavailable" }, 503));
    await expect(proposeCommand("world", "/move east", demoGameState, "hero")).rejects.toThrow("unavailable");
    await expect(loadGameState("world", "hero", cursor)).rejects.toThrow("unavailable");
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("rejects a declined command rather than refreshing it as an accepted action", async () => {
    vi.mocked(fetch).mockResolvedValue(ok({ result: { accepted: false }, event: { event_id: "event" } }));
    await expect(proposeCommand("world", "/move east", demoGameState, "hero")).rejects.toThrow(/not accepted/);
  });
});
