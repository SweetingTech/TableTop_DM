import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, GitBranch, Pause, Play, Rewind, Scale } from "lucide-react";
import { PageHeader, Panel, Stat, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { Trial } from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { compareTrials, loadRuns, loadTrialDetail, type TrialComparison } from "./api";
import { eventActor, eventSummary } from "./eventPresentation";

const TABS = ["Ledger", "Decisions", "Observations", "Beliefs", "Memories", "Replay"] as const;
type InspectorTab = typeof TABS[number];

export default function RunInspectorPage() {
  const resource = useAsyncResource(loadRuns, []);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [trialIndex, setTrialIndex] = useState(0);
  const [trial, setTrial] = useState<Trial | null>(null);
  const [trialSource, setTrialSource] = useState<"live" | "demo">("live");
  const [tab, setTab] = useState<InspectorTab>("Ledger");
  const [playing, setPlaying] = useState(false);
  const [replayIndex, setReplayIndex] = useState(0);
  const [comparison, setComparison] = useState<TrialComparison | null>(null);
  const [error, setError] = useState("");
  const jobs = resource.data?.data ?? [];
  const selectedJob = jobs.find((job) => job.job_id === selectedJobId) ?? jobs[0] ?? null;
  const trials = selectedJob?.report?.sample_trials ?? [];
  const trialSummary = trials[trialIndex] ?? null;

  useEffect(() => {
    if (!trialSummary) return;
    let active = true;
    loadTrialDetail(trialSummary.trial_id, trialSummary).then((result) => { if (active) { setTrial(result.data); setTrialSource(result.source); setReplayIndex(0); setComparison(null); } }, (reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Trial detail failed"));
    return () => { active = false; };
  }, [trialSummary]);

  useEffect(() => {
    if (!playing || !trial?.events?.length) return;
    const timer = window.setInterval(() => setReplayIndex((value) => value >= trial.events!.length - 1 ? 0 : value + 1), 900);
    return () => window.clearInterval(timer);
  }, [playing, trial?.events]);

  const trace = trial?.traces.at(-1);
  const chosen = trace?.candidates.find((candidate) => candidate.action === trace.chosen_action);
  const replayEvent = trial?.events?.[replayIndex];
  const nextTrial = trials.length ? trials[(trialIndex + 1) % trials.length] : null;

  async function runComparison() {
    if (!trial || !nextTrial) return;
    try { const result = await compareTrials(trial, nextTrial); setComparison(result.data); } catch (reason) { setError(reason instanceof Error ? reason.message : "Comparison failed"); }
  }

  if (resource.loading) return <LoadingState label="Loading run history" />;
  if (resource.error) return <ErrorState message={resource.error} retry={resource.reload} />;

  return (
    <div className="page run-page" data-testid="run-inspector">
      <SourceNotice source={resource.data?.source ?? "live"} reason={resource.data?.reason} />
      <SourceNotice source={trialSource} reason={trialSource === "demo" ? "Trial detail endpoint unavailable; deterministic demo data is shown." : undefined} />
      <PageHeader title="Run Inspector" description="Replay event causality, policy decisions, subjective state, and verifier evidence." actions={<button className="button" type="button" disabled={!trial || !nextTrial} onClick={runComparison}><Scale size={15} />Compare next trial</button>} />
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      <div className="run-layout">
        <Panel title="Runs" meta={<span>{jobs.length} recorded</span>} className="run-list-panel">
          <div className="selection-list" data-testid="run-list" role="listbox" aria-label="Runs">{jobs.map((job) => <button className={`selection-row ${job.job_id === selectedJob?.job_id ? "selected" : ""}`} type="button" role="option" aria-selected={job.job_id === selectedJob?.job_id} key={job.job_id} onClick={() => { if (job.job_id === selectedJob?.job_id) return; setSelectedJobId(job.job_id); setTrialIndex(0); setTrial(null); }}><span className="entity-sigil"><Play size={14} /></span><span><strong>{job.report?.scenario_id ?? job.kind}</strong><small>{job.completed} / {job.total} · {job.job_id}</small></span><Status value={job.status} /></button>)}</div>
        </Panel>
        <section className="run-detail">
          <div className="replay-bar">
            <div><strong>{selectedJob?.report?.scenario_id ?? "No run selected"}</strong><span>{trial ? `Trial ${trialIndex + 1} of ${trials.length}` : "No trial"}</span></div>
            <div className="replay-controls"><button type="button" aria-label="First trial" onClick={() => setTrialIndex(0)} disabled={!trials.length}><Rewind size={15} /></button><button type="button" aria-label="Previous trial" onClick={() => setTrialIndex((value) => Math.max(0, value - 1))} disabled={trialIndex === 0}><ChevronLeft size={15} /></button><button type="button" aria-label={playing ? "Pause replay" : "Play replay"} onClick={() => setPlaying((value) => !value)} disabled={!trial?.events?.length}>{playing ? <Pause size={15} /> : <Play size={15} />}</button><button type="button" aria-label="Next trial" onClick={() => setTrialIndex((value) => Math.min(trials.length - 1, value + 1))} disabled={trialIndex >= trials.length - 1}><ChevronRight size={15} /></button></div>
            <div className="replay-progress"><input aria-label="Replay event" type="range" min={0} max={Math.max(0, (trial?.events?.length ?? 1) - 1)} value={replayIndex} onChange={(event) => setReplayIndex(Number(event.target.value))} /><span>{replayEvent ? `${replayIndex + 1} / ${trial?.events?.length}` : "No ledger"}</span></div>
          </div>
          <div className="subnav inner" role="tablist" aria-label="Run evidence">{TABS.map((item) => <button type="button" role="tab" aria-selected={tab === item} className={tab === item ? "selected" : ""} key={item} onClick={() => setTab(item)}>{item}</button>)}</div>
          <Panel title={tab} meta={trial ? <Status value={trial.status} /> : undefined} className="evidence-panel">
            {!trial ? <EmptyState title="No trial selected" detail="Choose a completed run and trial." /> : <EvidenceTab tab={tab} trial={trial} replayIndex={replayIndex} />}
          </Panel>
          {comparison ? <Panel title="Trial comparison" meta={<span>{comparison.same_canonical_origin ? "Same canonical origin" : "Different origins"}</span>}><div className="stat-strip">{Object.entries(comparison.metric_deltas).map(([name, value]) => <Stat key={name} label={name.replaceAll("_", " ")} value={`${value >= 0 ? "+" : ""}${value.toFixed(2)}`} />)}</div></Panel> : null}
        </section>
        <aside className="run-inspector-panel">
          <Panel title="Branch lineage"><div className="lineage"><span>Canonical snapshot<strong className="mono">{trial?.canonical_hash_before ?? "—"}</strong></span><GitBranch size={18} /><span>Trial state<strong className="mono">{trial?.trial_state_hash ?? "—"}</strong></span></div></Panel>
          <Panel title="Decision audit">{trace ? <><dl className="definition-list"><dt>Actor</dt><dd className="mono">{trace.persona_id}</dd><dt>Action</dt><dd>{trace.chosen_action.replaceAll("_", " ")}</dd><dt>Runtime</dt><dd>{trace.runtime_kind ?? "—"}</dd><dt>Policy</dt><dd>{trace.policy_version}</dd></dl><h3>Factors</h3>{Object.entries(chosen?.factors ?? {}).map(([name, value]) => <div className="factor" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{value.toFixed(2)}</strong></div>)}</> : <EmptyState title="No decision trace" detail="This trial contains no recorded decision." />}</Panel>
          <Panel title="Current replay event">{replayEvent ? <article className="replay-event"><span>{replayEvent.event_type}</span><strong>{eventSummary(replayEvent)}</strong><small className="mono">{replayEvent.event_id}</small></article> : <EmptyState title="No replay event" detail="The trial has no detailed ledger events." />}</Panel>
        </aside>
      </div>
    </div>
  );
}

function EvidenceTab({ tab, trial, replayIndex }: { tab: InspectorTab; trial: Trial; replayIndex: number }) {
  if (tab === "Ledger" || tab === "Replay") return trial.events?.length ? <div className="ledger-list">{trial.events.map((event, index) => <article className={index === replayIndex ? "active" : ""} key={event.event_id}><time>{new Date(event.created_at).toLocaleTimeString()}</time><span className="mono">{event.event_type}</span><strong>{eventSummary(event)}</strong><small>{eventActor(event)}</small></article>)}</div> : <EmptyState title="No detailed ledger" detail="Only normalized trial output was retained." />;
  if (tab === "Decisions") return trial.traces.length ? <div className="decision-list">{trial.traces.map((trace) => <article key={trace.trace_id}><strong>{trace.chosen_action.replaceAll("_", " ")}</strong><span>{trace.policy_version}</span><small>seed {trace.seed} · {trace.candidates.length} candidates</small></article>)}</div> : <EmptyState title="No decisions" detail="This run recorded no policy traces." />;
  if (tab === "Observations") return trial.observations?.length ? <div className="evidence-list">{trial.observations.map((item) => <article key={item.observation_id}><strong>{item.summary}</strong><span>{Math.round(item.confidence * 100)}% confidence</span><small className="mono">{item.source_event_id}</small></article>)}</div> : <EmptyState title="No observations" detail="Observation artifacts were not retained for this trial." />;
  if (tab === "Beliefs") return trial.beliefs?.length ? <div className="evidence-list">{trial.beliefs.map((item) => <article key={item.belief_id}><strong>{item.predicate.replaceAll("_", " ")}</strong><span>{String(item.value)} · {Math.round(item.confidence * 100)}%</span>{item.contradicted_by_event_id ? <small>Contradicted by {item.contradicted_by_event_id}</small> : null}</article>)}</div> : <EmptyState title="No belief snapshot" detail="Belief artifacts were not retained for this trial." />;
  return trial.memories?.length ? <div className="evidence-list">{trial.memories.map((item) => <article key={item.memory_id}><strong>{item.summary}</strong><span>Importance {item.importance.toFixed(2)}</span><small>Emotional weight {item.emotional_weight.toFixed(2)}</small></article>)}</div> : <EmptyState title="No memories" detail="Memory artifacts were not retained for this trial." />;
}
