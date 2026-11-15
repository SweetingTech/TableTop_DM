import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../core/api/client";
import type { GameState, Sourced } from "../../core/api/types";
import { loadGameState, type CommandAcknowledgement } from "./api";

export const CONSOLE_POLL_MS = 2500;
type State = { data: Sourced<GameState> | null; loading: boolean; error: string; syncError: string };

export function useConsoleScene(world: string, viewpoint: string, accepted: CommandAcknowledgement | null) {
  const [state, setState] = useState<State>({ data: null, loading: true, error: "", syncError: "" });
  const [nonce, setNonce] = useState(0);
  const seen = useRef({ world, viewpoint, observer: "", version: -1 });
  const reload = useCallback(() => setNonce(value => value + 1), []);

  useEffect(() => {
    let active = true;
    let generation = 0;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let denied = false;
    if (seen.current.world !== world || seen.current.viewpoint !== viewpoint) {
      seen.current = { world, viewpoint, observer: "", version: -1 };
    }
    function schedule() {
      if (!active || denied) return;
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (document.visibilityState === "hidden") schedule();
        else void read(true);
      }, CONSOLE_POLL_MS);
    }
    async function read(background: boolean) {
      if (!active || denied) return;
      const request = ++generation;
      clearTimeout(timer);
      controller?.abort();
      const current = new AbortController();
      controller = current;
      if (!background) setState(previous => ({ ...previous, loading: true, error: "", syncError: "" }));
      try {
        if (accepted && !accepted.scene_refresh) {
          throw new Error("The server did not provide scene refresh status. Reload this page to read the scene.");
        }
        const result = await loadGameState(world, viewpoint || seen.current.observer, accepted?.scene_refresh ?? undefined, current.signal);
        if (!active || current.signal.aborted || request !== generation) return;
        const version = result.data.projection_version ?? -1;
        if (version < seen.current.version) {
          setState(previous => ({ ...previous, loading: false,
            syncError: "An older scene was ignored. Retrying synchronization…" }));
          return;
        }
        seen.current.version = version;
        seen.current.observer = result.data.observer_entity_id ?? "";
        setState({ data: result, loading: false, error: "", syncError: "" });
      } catch (error) {
        if (!active || current.signal.aborted || request !== generation) return;
        denied = error instanceof ApiError && [401, 403].includes(error.status);
        const message = error instanceof Error ? error.message : "Scene unavailable";
        setState(previous => background && previous.data && !denied
          ? { ...previous, loading: false, syncError: `Connection interrupted. Showing the last confirmed scene. ${message}` }
          : { data: null, loading: false, error: message, syncError: "" });
      } finally {
        if (active && request === generation) schedule();
      }
    }
    const reconnect = () => {
      if (document.visibilityState !== "hidden") void read(true);
    };
    void read(false);
    window.addEventListener("online", reconnect);
    window.addEventListener("focus", reconnect);
    document.addEventListener("visibilitychange", reconnect);
    return () => {
      active = false;
      ++generation;
      clearTimeout(timer);
      controller?.abort();
      window.removeEventListener("online", reconnect);
      window.removeEventListener("focus", reconnect);
      document.removeEventListener("visibilitychange", reconnect);
    };
  }, [world, viewpoint, accepted, nonce]);

  return { ...state, reload };
}
