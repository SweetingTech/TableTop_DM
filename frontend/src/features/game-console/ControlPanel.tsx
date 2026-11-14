import { useEffect, useRef, useState } from "react";
import { Panel } from "../../components/ui/Primitives";
import { handoffController, loadController, type ControllerScope, type ControllerState, type ControlMode } from "./api";

export default function ControlPanel({ scope, onModeChange, onProgress }: {
  scope: ControllerScope;
  onModeChange: (mode: ControlMode | "UNAVAILABLE", epoch?: number) => void;
  onProgress: (step: number) => void;
}) {
  const [control, setControl] = useState<ControllerState | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [limitText, setLimitText] = useState("20");
  const limit = Number(limitText);
  const [revision, setRevision] = useState(0);
  const initializedLimit = useRef(false);
  const actionGeneration = useRef(0);
  const retry = useRef<{ mode: ControlMode; epoch: number; limit: number; key: string } | null>(null);
  const { world, branch, run, entity } = scope;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
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

  async function change(mode: ControlMode) {
    const generation = actionGeneration.current;
    const epoch = control?.epoch ?? 0;
    const pending = retry.current;
    const operation = pending && pending.mode === mode && pending.epoch === epoch && pending.limit === limit
      ? pending : { mode, epoch, limit, key: crypto.randomUUID() };
    retry.current = operation;
    setBusy(true); setError("");
    try {
      await handoffController({ world, branch, run, entity }, mode, epoch, limit, operation.key);
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

  const mode = control?.mode ?? "HUMAN";
  return <Panel title="Character control" meta={<span role="status">{loaded ? mode === "HUMAN" ? "You are playing" : mode === "AUTONOMOUS" ? "Character is acting" : "Autonomy paused" : "Loading control…"}</span>}>
    <p>Your character uses human history and its pinned persona to speak, move, guard, or respond to visible threats with available spells. When your operator configures a dialogue provider, replies use generated speech. Closing the page keeps your selected control mode.</p>
    <p>{control ? `${control.step} / ${control.max_steps} autonomous actions` : "Autonomy is off until you enable it."}{control?.last_error ? ` · ${control.last_error === "step_limit" ? "Action limit reached." : "The runner paused or is waiting. Take control or explicitly resume."}` : ""}</p>
    <label>Autonomous action limit<input aria-label="Autonomous action limit" type="number" min={1} max={1000} value={limitText} disabled={!loaded || busy} onChange={(event) => setLimitText(event.target.value)} /></label>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      <button className="button" type="button" disabled={!loaded || busy || Boolean(error) || mode === "AUTONOMOUS" || !Number.isInteger(limit) || limit < 1 || limit > 1000} onClick={() => void change("AUTONOMOUS")}>Let character act</button>
      <button className="button" type="button" disabled={!loaded || busy || mode === "HUMAN"} onClick={() => void change("HUMAN")}>Take control</button>
      <button className="button" type="button" disabled={!loaded || busy || mode !== "AUTONOMOUS"} onClick={() => void change("PAUSED")}>Pause autonomy</button>
    </div>
    {error ? <p className="field-error" role="alert">{error} <button type="button" className="button" onClick={() => setRevision((value) => value + 1)}>Reload control</button></p> : null}
  </Panel>;
}
