import { useEffect, useMemo, useState } from "react";
import { Check, CircleStop, Download, Play, RotateCcw, ShieldCheck } from "lucide-react";
import { PageHeader, Panel, Stat, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { CohortReport, DataSource, JobSummary, Trial } from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { cancelJob, launchScenario, loadJob, loadScenarios, retryJob } from "./api";

const ONBOARDING_STEPS = ["Welcome", "Learn controls", "Complete task", "Claim reward", "Choose path", "Onboarded"];
const GENERIC_STEPS = ["Snapshot", "Sample", "Branch trials", "Verify", "Aggregate"];

export default function ScenarioLabPage() {
  const resource = useAsyncResource(loadScenarios, []);
  const [scenarioId, setScenarioId] = useState("");
  const [cohortSize, setCohortSize] = useState(100);
  const [seedText, setSeedText] = useState("101, 202, 303");
  const [job, setJob] = useState<JobSummary | null>(null);
  const [report, setReport] = useState<CohortReport | null>(null);
  const [selected, setSelected] = useState<Trial | null>(null);
  const [runSource, setRunSource] = useState<DataSource>("live");
  const [runReason, setRunReason] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const scenarios = resource.data?.data ?? [];
  const selectedScenario = scenarios.find((item) => item.scenario_id === scenarioId) ?? scenarios[0];
  const steps = selectedScenario?.scenario_id.includes("onboarding") ? ONBOARDING_STEPS : GENERIC_STEPS;
  const seeds = useMemo(() => seedText.split(",").map((item) => Number(item.trim())).filter(Number.isFinite), [seedText]);

  useEffect(() => {
    if (!job || ["COMPLETED", "FAILED", "CANCELLED", "STOPPED"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      loadJob(job.job_id).then((next) => {
        setJob(next);
        if (next.report) { setReport(next.report); setSelected(next.report.sample_trials[0] ?? null); }
      }, (reason: unknown) => setError(reason instanceof Error ? reason.message : "Job polling failed"));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job]);

  async function runScenario() {
    if (!selectedScenario || !seeds.length) return;
    setWorking(true); setError(""); setReport(null); setSelected(null);
    try {
      const result = await launchScenario(selectedScenario, cohortSize, seeds);
      setRunSource(result.source); setRunReason(result.reason ?? ""); setJob(result.data.job); setReport(result.data.report); setSelected(result.data.report?.sample_trials[0] ?? null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Scenario launch failed"); } finally { setWorking(false); }
  }

  async function stopJob() {
    if (!job) return;
    try { setJob(await cancelJob(job.job_id)); } catch (reason) { setError(reason instanceof Error ? reason.message : "Cancellation failed"); }
  }

  async function rerunJob() {
    if (!job) { await runScenario(); return; }
    try { const next = await retryJob(job.job_id); setJob(next); setReport(next.report ?? null); } catch (reason) { setError(reason instanceof Error ? reason.message : "Retry failed"); }
  }

  function exportReport() {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${report.scenario_id}-${report.scenario_version}.json`; anchor.click(); URL.revokeObjectURL(url);
  }

  if (resource.loading) return <LoadingState label="Loading scenario registry" />;
  if (resource.error) return <ErrorState message={resource.error} retry={resource.reload} />;
  if (!selectedScenario) return <EmptyState title="No scenario definitions" detail="Register a scenario before launching trials." />;
  const progress = job ? Math.round(job.progress * 100) : report ? Math.round(report.completion_rate * 100) : 0;

  return (
    <div className="page scenario-page">
      <SourceNotice source={runSource === "demo" ? runSource : resource.data?.source ?? "live"} reason={runSource === "demo" ? runReason : resource.data?.reason} />
      <PageHeader title="Scenario Lab" description="Run and inspect registered branch-isolated experiment definitions across simulated players." actions={<><button className="button primary" type="button" onClick={runScenario} disabled={working || Boolean(job && !["COMPLETED", "FAILED", "CANCELLED", "STOPPED"].includes(job.status))}><Play size={15} fill="currentColor" />{working ? "Launching…" : report ? "Run again" : "Run scenario"}</button><button className="button" type="button" onClick={stopJob} disabled={!job || ["COMPLETED", "FAILED", "CANCELLED", "STOPPED"].includes(job.status)}><CircleStop size={15} />Stop</button><button className="button" type="button" onClick={rerunJob} disabled={!job || !["FAILED", "CANCELLED", "STOPPED"].includes(job.status)}><RotateCcw size={15} />Retry</button><button className="button" type="button" onClick={exportReport} disabled={!report}><Download size={15} />Export</button></>} />
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      <div className="scenario-workspace">
        <div className="scenario-main">
          <section className="scenario-overview">
            <Panel title="Run cohort" className="scenario-config">
              <label>Scenario<select value={selectedScenario.scenario_id} onChange={(event) => setScenarioId(event.target.value)}>{scenarios.map((item) => <option key={item.scenario_id} value={item.scenario_id}>{item.name} · {item.version}</option>)}</select></label>
              <div className="form-pair"><label>Cohort size<input type="number" min={1} max={10000} value={cohortSize} onChange={(event) => setCohortSize(Number(event.target.value))} /></label><label>Seeds<input value={seedText} onChange={(event) => setSeedText(event.target.value)} /></label></div>
              <p>{selectedScenario.description}</p>
              <dl className="definition-list"><dt>Status</dt><dd><Status value={job?.status ?? selectedScenario.status} /></dd><dt>Trials</dt><dd>{cohortSize * seeds.length}</dd><dt>Verifiers</dt><dd>{selectedScenario.verifier_versions.length}</dd></dl>
            </Panel>
            <Panel title="Trial progress" meta={<span>{job ? `${job.completed} / ${job.total}` : report ? `${report.completed} / ${report.trial_count}` : `0 / ${cohortSize * seeds.length}`}</span>} className="progress-panel">
              <div className="progress-number"><strong>{progress}%</strong><span>{job?.status ?? (report ? "COMPLETED" : "READY")}</span></div><div className="progress-line"><div style={{ width: `${progress}%` }} /></div>
              <div className="step-track">{steps.map((step, index) => <div className={report ? "step complete" : progress > index / steps.length * 100 ? "step active" : "step"} key={step}><span>{report ? <Check size={14} /> : index + 1}</span><strong>{step}</strong></div>)}</div>
            </Panel>
          </section>
          <Panel title="Cohort summary" meta={report?.canonical_world_unchanged ? <span className="safe"><ShieldCheck size={15} />Canonical world unchanged</span> : undefined} className="summary-panel">
            <div className="stat-strip five"><Stat label="Completion" value={report ? `${Math.round(report.completion_rate * 100)}%` : "—"} />{metricEntries(report).map(([name, value]) => <Stat key={name} label={name.replaceAll("_", " ")} value={formatMetric(value)} />)}</div>
            {report ? <TrialTable report={report} selected={selected} onSelect={setSelected} /> : <EmptyState title="No normalized trial facts" detail="Launch the selected scenario to populate the cohort report." />}
          </Panel>
          <Panel title="Run log" meta={<span>Deterministic execution</span>} className="run-log-panel">
            <div className="log-line"><span>INFO</span><strong>runner</strong><p>{report ? `Completed ${report.trial_count} branch-isolated trials.` : job ? `Job ${job.job_id} is ${job.status.toLowerCase()}.` : "Scenario contract validated and ready."}</p></div>
            <div className="log-line"><span>INFO</span><strong>verifier</strong><p>{report?.canonical_world_unchanged ? "Canonical world hash verified unchanged." : "Awaiting verifier facts."}</p></div>
          </Panel>
        </div>
        <TrialInspector trial={selected} />
      </div>
    </div>
  );
}

function metricEntries(report: CohortReport | null) { return Object.entries(report?.metrics ?? {}).slice(0, 4); }
function formatMetric(value: number) { return Number.isInteger(value) ? String(value) : value.toFixed(3); }

function TrialTable({ report, selected, onSelect }: { report: CohortReport; selected: Trial | null; onSelect: (trial: Trial) => void }) {
  const metricNames = [...new Set(report.sample_trials.flatMap((trial) => Object.keys(trial.metrics)))].slice(0, 4);
  return <div className="data-table-wrap" data-testid="scenario-results"><table><thead><tr><th>Persona</th><th>Seed</th><th>Status</th><th>Steps</th>{metricNames.map((name) => <th key={name}>{name.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{report.sample_trials.map((trial) => <tr className={selected?.trial_id === trial.trial_id ? "selected" : ""} key={trial.trial_id} tabIndex={0} aria-selected={selected?.trial_id === trial.trial_id} onClick={() => onSelect(trial)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(trial); } }}><td className="mono">{trial.persona_id?.slice(0, 16) ?? "aggregate"}</td><td>{trial.seed}</td><td><Status value={trial.status} /></td><td>{trial.steps}</td>{metricNames.map((name) => <td key={name}>{String(trial.metrics[name] ?? "—")}</td>)}</tr>)}</tbody></table></div>;
}

function TrialInspector({ trial }: { trial: Trial | null }) {
  const trace = trial?.traces.at(-1); const chosen = trace?.candidates.find((candidate) => candidate.action === trace.chosen_action);
  return <aside className="trial-inspector"><div className="inspector-heading"><h2>Decision trace</h2><span>{trial ? `${trial.steps} steps` : "No trial"}</span></div>{!trial ? <EmptyState title="Select a trial" detail="Choose a keyboard-focusable trial row to inspect recorded evidence." /> : <><section><h3>Trial</h3><dl className="definition-list"><dt>ID</dt><dd className="mono">{trial.trial_id}</dd><dt>Persona</dt><dd className="mono">{trial.persona_id}</dd><dt>Seed</dt><dd>{trial.seed}</dd><dt>Status</dt><dd><Status value={trial.status} /></dd></dl></section>{trace ? <><section><h3>Chosen action</h3><strong className="chosen-value">{trace.chosen_action.replaceAll("_", " ")}</strong><p className="muted">{trace.runtime_kind ?? "Runtime not recorded"} · {trace.policy_version}</p></section><section><h3>Policy factors</h3>{Object.entries(chosen?.factors ?? {}).map(([name, value]) => <div className="factor" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{value.toFixed(2)}</strong></div>)}</section></> : <section><EmptyState title="No decision trace" detail="This trial did not record a deliberation trace." /></section>}<section><h3>Verifier facts</h3>{trial.facts.length ? trial.facts.map((fact) => <div className="fact" key={`${fact.fact_type}-${fact.verifier_version}`}><Check size={14} /><span>{fact.fact_type.replaceAll(".", " ")}</span><strong>{String(fact.value)}</strong><small>{fact.evidence_event_ids.length} evidence links</small></div>) : <p className="muted">No verifier facts recorded.</p>}</section><section><h3>Integrity</h3><dl className="definition-list"><dt>Before</dt><dd className="mono">{trial.canonical_hash_before}</dd><dt>After</dt><dd className="mono">{trial.canonical_hash_after}</dd><dt>Trial state</dt><dd className="mono">{trial.trial_state_hash}</dd></dl></section></>}</aside>;
}
