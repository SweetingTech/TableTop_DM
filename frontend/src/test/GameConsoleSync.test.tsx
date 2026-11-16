import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../core/api/client";
import type { GameState, Sourced } from "../core/api/types";
import { loadGameState } from "../features/game-console/api";
import { CONSOLE_POLL_MS, useConsoleScene } from "../features/game-console/useConsoleScene";
import { mapLayout } from "../features/game-console/mapPosition";

vi.mock("../features/game-console/api", () => ({ loadGameState: vi.fn() }));
function scene(version: number, observations = 0): Sourced<GameState> {
  return { source: "live", data: { run: null, branch: null, entities: [], turn: 0,
    events: Array.from({ length: observations }, (_, index) => ({ event_id: String(index), event_type: "heard", created_at: "" })),
    observer_entity_id: "hero", projection_version: version, interaction_status: "ACTIVE" } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => { vi.useFakeTimers(); vi.mocked(loadGameState).mockReset(); });
afterEach(() => vi.useRealTimers());

describe("continuous perception-scoped scene synchronization", () => {
  it("polls the pinned observer, accepts newly projected observations at the same version, and ignores older versions", async () => {
    vi.mocked(loadGameState).mockResolvedValueOnce(scene(4)).mockResolvedValueOnce(scene(4, 1)).mockResolvedValue(scene(3));
    const { result } = renderHook(() => useConsoleScene("world", "", null));
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_MS); });
    expect(result.current.data?.data.events).toHaveLength(1);
    expect(vi.mocked(loadGameState).mock.calls[1][1]).toBe("hero");
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_MS); });
    expect(result.current.data?.data.projection_version).toBe(4);
    expect(result.current.syncError).toMatch(/older scene was ignored/);
  });

  it("reconnects and prevents an obsolete response from replacing a newer scene", async () => {
    const old = deferred<Sourced<GameState>>();
    vi.mocked(loadGameState).mockResolvedValueOnce(scene(1)).mockImplementationOnce(() => old.promise).mockResolvedValue(scene(3));
    const { result } = renderHook(() => useConsoleScene("world", "hero", null));
    await act(async () => {});
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    await act(async () => { window.dispatchEvent(new Event("online")); });
    expect(result.current.data?.data.projection_version).toBe(3);
    expect(vi.mocked(loadGameState).mock.calls[1][3]?.aborted).toBe(true);
    await act(async () => old.resolve(scene(2)));
    expect(result.current.data?.data.projection_version).toBe(3);
  });

  it("clears revoked access and stops automatic reads until an explicit retry", async () => {
    vi.mocked(loadGameState).mockResolvedValueOnce(scene(1)).mockRejectedValue(new ApiError("access denied", 403));
    const { result } = renderHook(() => useConsoleScene("world", "hero", null));
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_MS); });
    expect(result.current.data).toBeNull(); expect(result.current.error).toBe("access denied");
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_MS * 3); });
    expect(loadGameState).toHaveBeenCalledTimes(2);
    vi.mocked(loadGameState).mockResolvedValue(scene(2));
    await act(async () => result.current.reload());
    expect(result.current.data?.data.projection_version).toBe(2);
  });

  it("labels interrupted reads and resynchronizes without replacing live data with demo data", async () => {
    vi.mocked(loadGameState).mockResolvedValueOnce(scene(1)).mockRejectedValueOnce(new ApiError("offline", 0)).mockResolvedValue(scene(2));
    const { result } = renderHook(() => useConsoleScene("world", "hero", null));
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(CONSOLE_POLL_MS); });
    expect(result.current.data?.source).toBe("live"); expect(result.current.syncError).toMatch(/last confirmed/);
    await act(async () => { window.dispatchEvent(new Event("online")); });
    expect(result.current.data?.data.projection_version).toBe(2); expect(result.current.syncError).toBe("");
  });
});

it("uses configured extents, and switches to an explicit grid for out-of-map known coordinates", () => {
  const presentation = { zone_id: "world", name: "Yard", min_x: -2, max_x: 2, min_y: -2, max_y: 2, image_path: "/static/yard.png" };
  expect(mapLayout([{ public_state: { x: 0, y: 0 } }], presentation).imagePath).toBe("/static/yard.png");
  const layout = mapLayout([{ public_state: { x: -20, y: 30 } }], presentation);
  expect(layout.imagePath).toBeNull(); expect(layout.bounds).toMatchObject({ min_x: -21, max_x: -19, min_y: 29, max_y: 31 });
});
