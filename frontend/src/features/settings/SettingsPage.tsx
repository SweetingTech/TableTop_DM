import { useState } from "react";
import { CheckCircle2, Database, KeyRound, Radio, ServerCog, ShieldCheck } from "lucide-react";
import { useAppContext } from "../../app/AppContext";
import { DefinitionList, PageHeader, Panel, Stat, Status } from "../../components/ui/Primitives";
import { ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import { getOperatorToken, setOperatorToken } from "../../core/api/client";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { loadSettings, updateTelemetry, verifyAccess } from "./api";

export default function SettingsPage() {
  const resource = useAsyncResource(loadSettings, []);
  const { refresh: refreshShell } = useAppContext();
  const [token, setToken] = useState(getOperatorToken);
  const [savedToken, setSavedToken] = useState(getOperatorToken);
  const [telemetryOverride, setTelemetryOverride] = useState<boolean | null>(null);
  const [working, setWorking] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const payload = resource.data?.data;
  const telemetryEnabled = telemetryOverride ?? payload?.telemetry.human_telemetry_enabled ?? false;

  async function saveAccess() {
    setOperatorToken(token); setSavedToken(token.trim()); setWorking("access"); setError(""); setMessage("");
    try { await verifyAccess(); setMessage("Operator access verified for this browser session."); refreshShell(); resource.reload(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Access verification failed"); } finally { setWorking(""); }
  }

  async function changeTelemetry(enabled: boolean) {
    const previous = telemetryEnabled;
    setTelemetryOverride(enabled);
    setWorking("telemetry"); setError(""); setMessage("");
    try { const result = await updateTelemetry(enabled); setTelemetryOverride(result.data.human_telemetry_enabled); setMessage(result.data.human_telemetry_enabled ? "Local human telemetry enabled." : "Human telemetry disabled."); } catch (reason) { setTelemetryOverride(previous); setError(reason instanceof Error ? reason.message : "Telemetry update failed"); } finally { setWorking(""); }
  }

  return (
    <div className="page settings-page">
      {resource.data ? <SourceNotice source={resource.data.source} reason={resource.data.reason} /> : null}
      <PageHeader
        title="Settings"
        description="Inspect local engine contracts, operator access, telemetry, and storage boundaries."
        actions={
          <Status
            value={
              resource.loading
                ? "CONNECTING"
                : resource.error
                  ? "ACCESS REQUIRED"
                  : resource.data?.source === "live"
                    ? "LOCAL ENGINE READY"
                    : "DEMO FALLBACK"
            }
          />
        }
      />
      {(message || error) ? <div className={`toast ${error ? "error" : "success"}`} role={error ? "alert" : "status"}>{error || message}</div> : null}
      <div className="settings-layout">
        <Panel title="Engine health" meta={<span className="safe"><CheckCircle2 size={15} />Contract available</span>} className="settings-engine">
          {resource.loading && !payload ? (
            <LoadingState label="Loading local settings" />
          ) : resource.error && !payload ? (
            <ErrorState message={resource.error} retry={resource.reload} />
          ) : payload ? (
            <>
              <div className="stat-strip"><Stat label="Kernel" value={payload.meta.kernel} /><Stat label="Contract" value={payload.meta.contract_version} /><Stat label="Persona schema" value={payload.meta.persona_schema_version} /><Stat label="Dimensions" value={payload.meta.persona_dimensions} /></div>
              <div className="diagnostic-grid"><div><ServerCog /><strong>Simulation engine</strong><span>{resource.data?.source === "live" ? "Responding" : "Endpoint unavailable"}</span></div><div><Database /><strong>Storage</strong><span>Not reported by meta contract</span></div><div><Radio /><strong>Realtime transport</strong><span>Not reported by meta contract</span></div><div><ShieldCheck /><strong>v1 migration</strong><span>{payload.meta.migrations_from_v1_supported ? "Supported" : "Clean-break v2"}</span></div></div>
            </>
          ) : null}
        </Panel>
        <Panel title="Operator access" className="settings-access">
          <p className="panel-intro">Enter the token printed by the lifecycle manager when this installation requires operator authorization. It is kept only for this browser session.</p>
          <label>Operator token<input type="password" autoComplete="off" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Optional on localhost" /></label>
          <div className="button-row"><button className="button primary" type="button" onClick={saveAccess} disabled={working === "access" || !token.trim()}><KeyRound size={15} />{working === "access" ? "Verifying…" : "Save and verify"}</button>{savedToken ? <button className="button" type="button" onClick={() => { setToken(""); setOperatorToken(""); setSavedToken(""); setMessage("Session token cleared."); }}>Clear token</button> : null}</div>
        </Panel>
        <Panel title="Telemetry" meta={<Status value={telemetryEnabled ? "ENABLED" : "DISABLED"} />} className="settings-telemetry">
          <label className="switch-row"><span><strong>Human telemetry</strong><small>Capture consented playtest measurements for local calibration.</small></span><input aria-busy={working === "telemetry"} aria-label="Human telemetry" data-testid="telemetry-setting" type="checkbox" checked={telemetryEnabled} disabled={!payload || Boolean(resource.error)} onChange={(event) => changeTelemetry(event.target.checked)} /></label>
          <DefinitionList items={[["Location", payload ? (payload.telemetry.local_only ? "Local machine only" : "External sink configured") : "Unlock operator access to inspect"], ["Default", "Disabled"], ["Synthetic label", "Hypothesis, never human ground truth"]]} />
        </Panel>
        <Panel title="Runtime boundaries" className="settings-runtime">
          <ul className="boundary-list"><li><span>1</span><p><strong>Models never own world truth.</strong> All mutation crosses typed command validation.</p></li><li><span>2</span><p><strong>Trials stay isolated.</strong> Canonical promotion requires explicit review.</p></li><li><span>3</span><p><strong>Seeds and versions travel together.</strong> Replays retain their causal context.</p></li></ul>
        </Panel>
      </div>
    </div>
  );
}
