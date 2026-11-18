import { useEffect, useRef, useState } from "react";
import { Panel } from "../../components/ui/Primitives";
import { handoffController, loadCharacterRecap, loadController, renewControllerPresence,
  type CharacterRecap, type ControllerScope, type ControllerState, type ControlMode } from "./api";

const disconnectOptions = [15, 60, 300];
type RecapRead = { key: string } & (
  { status: "loading" } | { status: "failed"; message: string } |
  { status: "ready"; data: CharacterRecap }
);

export default function ControlPanel({ scope, onModeChange, onProgress }: {
  scope: ControllerScope;
  onModeChange: (mode: ControlMode | "UNAVAILABLE", epoch?: number) => void;
  onProgress: (step: number) => void;
}) {
  const [control, setControl] = useState<ControllerState | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [recap, setRecap] = useState<RecapRead | null>(null);
  const [limitText, setLimitText] = useState("20");
  const limit = Number(limitText);
  const [revision, setRevision] = useState(0);
  const initializedLimit = useRef(false);
  const actionGeneration = useRef(0);
  const retry = useRef<{
    mode: ControlMode; epoch: number; limit: number; key: string; timeout?: number | null;
  } | null>(null);
  const recapRequest = useRef<AbortController | null>(null);
  const { world, branch, run, entity } = scope;
  const recapKey = `${world}/${branch}/${run}/${entity}`;

  useEffect(() => () => recapRequest.current?.abort(), [world, branch, run, entity]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    let nextPresenceAt = 0;
    let presenceEpoch: number | undefined;
    const read = async () => {
      try {
        const result = await loadController({ world, branch, run, entity }, controller.signal);
        if (!active) return;
        const current = result.control;
        if (!initializedLimit.current) {
          setLimitText(String(current?.max_steps ?? 20));
          initializedLimit.current = true;
        }
        setControl(current); setLoaded(true); setError("");
        onModeChange(current?.mode ?? "HUMAN", current?.epoch);
        onProgress(current?.step ?? 0);
        if (current?.mode === "HUMAN" && current.disconnect_after_seconds &&
          (presenceEpoch !== current.epoch || Date.now() >= nextPresenceAt)) {
          await renewControllerPresence({ world, branch, run, entity }, current.epoch, controller.signal);
          presenceEpoch = current.epoch;
          nextPresenceAt = Date.now() + 5000;
        }
      } catch (failure) {
        if (!active) return;
        setError(failure instanceof Error ? failure.message : "Could not read character control.");
        onModeChange("UNAVAILABLE");
      } finally {
        if (active) timer = setTimeout(read, 1000);
      }
    };
    void read();
    return () => { active = false; actionGeneration.current += 1; controller.abort(); clearTimeout(timer); };
  }, [world, branch, run, entity, revision, onModeChange, onProgress]);

  async function change(mode: ControlMode, timeout?: number | null) {
    const generation = actionGeneration.current;
    const epoch = control?.epoch ?? 0;
    const pending = retry.current;
    const operation = pending && pending.mode === mode && pending.epoch === epoch &&
      pending.limit === limit && pending.timeout === timeout
      ? pending : { mode, epoch, limit, key: crypto.randomUUID(), timeout };
    retry.current = operation;
    setBusy(true); setError("");
    try {
      await handoffController({ world, branch, run, entity }, mode, epoch, limit, operation.key, timeout);
      if (generation !== actionGeneration.current) return;
      retry.current = null;
      setRevision((value) => value + 1);
    } catch (failure) {
      if (generation !== actionGeneration.current) return;
      setError(failure instanceof Error ? failure.message : "Handoff failed; reload control and retry.");
    } finally {
      if (generation === actionGeneration.current) setBusy(false);
    }
  }

  async function reviewRecap() {
    recapRequest.current?.abort();
    const controller = new AbortController();
    recapRequest.current = controller;
    setRecap({ key: recapKey, status: "loading" });
    try {
      const data = await loadCharacterRecap(scope, controller.signal);
      if (!controller.signal.aborted) setRecap({ key: recapKey, status: "ready", data });
    } catch (failure) {
      if (!controller.signal.aborted) setRecap({ key: recapKey, status: "failed",
        message: failure instanceof Error ? failure.message : "Could not read character recap." });
    }
  }

  const mode = control?.mode ?? "HUMAN";
  const timeout = control?.disconnect_after_seconds ?? 0;
  const validLimit = Number.isInteger(limit) && limit >= 1 && limit <= 1000;
  const activeRecap = recap?.key === recapKey ? recap : null;
  return <Panel title="Character control" meta={<span role="status">{loaded ? mode === "HUMAN" ? "You are playing" : mode === "AUTONOMOUS" ? "Character is acting" : "Autonomy paused" : "Loading control…"}</span>}>
    <p>Your character draws on your play history and its persona. A paused world stops autonomous actions.</p>
    <p>{control ? `${control.step} / ${control.max_steps} autonomous actions` : "Autonomy is off until you enable it."}{control?.last_error ? ` · ${control.last_error === "step_limit" ? "Action limit reached." : "The runner paused or is waiting. Take control or explicitly resume."}` : ""}</p>
    {control?.handoff_reason === "DISCONNECT_TIMEOUT" ? <p>Connection timed out. Take control when ready.</p> : null}
    <label>Autonomous action limit<input aria-label="Autonomous action limit" type="number" min={1} max={1000} value={limitText} disabled={!loaded || busy} onChange={(event) => setLimitText(event.target.value)} /></label>
    <label>On disconnect<select aria-label="On disconnect" value={timeout}
      disabled={!loaded || busy || Boolean(error) || mode !== "HUMAN" || !validLimit}
      onChange={(event) => void change("HUMAN", Number(event.target.value) || null)}>
      <option value={0}>Keep me in control</option>
      {disconnectOptions.map((seconds) => <option key={seconds} value={seconds}>Let character act after {seconds} seconds</option>)}
      {timeout && !disconnectOptions.includes(timeout) ? <option value={timeout}>Let character act after {timeout} seconds</option> : null}
    </select></label>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      <button className="button" type="button" disabled={!loaded || busy || Boolean(error) || mode === "AUTONOMOUS" || !validLimit} onClick={() => void change("AUTONOMOUS")}>Let character act</button>
      <button className="button" type="button" disabled={!loaded || busy || mode === "HUMAN"} onClick={() => void change("HUMAN")}>Take control</button>
      <button className="button" type="button" disabled={!loaded || busy || mode !== "AUTONOMOUS"} onClick={() => void change("PAUSED")}>Pause autonomy</button>
      {control && (mode !== "HUMAN" || control.epoch > 1) ? <button className="button" type="button"
        disabled={activeRecap?.status === "loading"} onClick={() => void reviewRecap()}>Show character recap</button> : null}
    </div>
    {activeRecap?.status === "failed" ? <p className="field-error" role="alert">{activeRecap.message}</p> : null}
    {activeRecap?.status === "loading" ? <p role="status">Reading character recap…</p> : null}
    {activeRecap?.status === "ready" ? <section aria-label="Character recap">
      {activeRecap.data.entries.length ? <ul>{activeRecap.data.entries.map((entry) =>
        <li key={entry.narration_id}>{entry.text}</li>)}</ul> :
        <p>{activeRecap.data.available ? "No narrated experiences during this handoff." : "No recorded handoff recap yet."}</p>}
    </section> : null}
    {error ? <p className="field-error" role="alert">{error} <button type="button" className="button" onClick={() => setRevision((value) => value + 1)}>Reload control</button></p> : null}
  </Panel>;
}
