import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../core/api/client";
import { getCharacterState, type CharacterRecord, type CharacterState } from "./api";

type State = { key: string; data: CharacterState | null; loading: boolean; error: string };

export function useCharacterState(character: CharacterRecord) {
  const id = character.character_id;
  const key = [id, character.world_id, character.entity_id, character.card_version, character.updated_at].join(":");
  const [state, setState] = useState<State>(() => ({ key, data: null, loading: true, error: "" }));
  const [revision, setRevision] = useState(0);
  const refresh = useCallback(() => {
    setState({ key, data: null, loading: true, error: "" });
    setRevision((value) => value + 1);
  }, [key]);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    let stop = false;
    let timer: number | undefined;
    const controller = new AbortController();
    const schedule = () => { if (!cancelled && !stop) timer = window.setTimeout(() => void load(), 5000); };
    async function load() {
      if (cancelled || inFlight || stop) return;
      window.clearTimeout(timer);
      if (document.visibilityState === "hidden") { schedule(); return; }
      inFlight = true;
      try {
        const data = await getCharacterState(id, controller.signal);
        if (!cancelled) setState({ key, data, loading: false, error: "" });
      } catch (reason) {
        if (cancelled || controller.signal.aborted) return;
        stop = reason instanceof ApiError && [401, 403].includes(reason.status);
        const error = reason instanceof ApiError && reason.status === 403
          ? "You no longer have access to this character's campaign state."
          : "Unable to load character state. Refresh to try again.";
        setState({ key, data: null, loading: false, error });
      } finally { inFlight = false; schedule(); }
    }
    const visible = () => { if (document.visibilityState !== "hidden") void load(); };
    void load();
    document.addEventListener("visibilitychange", visible);
    return () => { cancelled = true; controller.abort(); window.clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [id, key, revision]);

  return { ...(state.key === key ? state : { data: null, loading: true, error: "" }), refresh };
}
