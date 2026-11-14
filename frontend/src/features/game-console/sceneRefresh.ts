import type { EventRecord, PerceivedScene } from "../../core/api/types";

export type SceneRefreshCursor = {
  world_id: string;
  branch_id: string;
  observer_entity_id: string;
  event_id: string;
  projection_version: number;
};

export const SCENE_REFRESH_TIMEOUT_MS = 8000;
export const SCENE_REFRESH_POLL_MS = 200;

export function uniqueObservations(events: EventRecord[]): EventRecord[] {
  const result = new Map<string, EventRecord>();
  for (const event of events) result.set(event.source_event_id ?? event.event_id, event);
  return [...result.values()];
}

function delay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const aborted = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", aborted);
      reject(new DOMException("Scene refresh cancelled", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", aborted);
      resolve();
    }, SCENE_REFRESH_POLL_MS);
    signal.addEventListener("abort", aborted, { once: true });
    if (signal.aborted) aborted();
  });
}

export async function waitForScene(
  load: (signal: AbortSignal) => Promise<PerceivedScene>,
  cursor: SceneRefreshCursor,
  signal?: AbortSignal,
): Promise<PerceivedScene> {
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) cancel();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, SCENE_REFRESH_TIMEOUT_MS);
  try {
    while (!controller.signal.aborted) {
      const scene = await load(controller.signal);
      if (controller.signal.aborted) throw new DOMException("Scene refresh cancelled", "AbortError");
      if (scene.world_id !== cursor.world_id || scene.branch_id !== cursor.branch_id
        || scene.observer_entity_id !== cursor.observer_entity_id) {
        throw new Error("The scene no longer matches the selected world and character.");
      }
      if (scene.refresh && scene.refresh.event_id !== cursor.event_id) {
        throw new Error("The scene did not acknowledge this action.");
      }
      if (scene.projection_version >= cursor.projection_version && scene.refresh?.ready) return scene;
      await delay(controller.signal);
    }
    throw new DOMException("Scene refresh cancelled", "AbortError");
  } catch (error) {
    if (timedOut) throw new Error("The scene is still updating. Retry the scene refresh.", { cause: error });
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}
