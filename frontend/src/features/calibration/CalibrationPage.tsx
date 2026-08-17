import { useState } from "react";
import { CheckCircle2, Rocket, Scale, ShieldAlert } from "lucide-react";
import { DefinitionList, PageHeader, Panel, Stat, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { CalibrationReport, DataSource } from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import {
  compareCalibration,
  loadCalibrationDetail,
  loadCalibrationHistory,
  promoteCalibration,
  reviewCalibration,
} from "./api";

const DEFAULT_METRICS = [
  { name: "completion_rate", synthetic: 0.91, human: 0.87 },
  { name: "comprehension_rate", synthetic: 0.94, human: 0.9 },
  { name: "mean_help_requests", synthetic: 0.25, human: 0.31 },
];

export default function CalibrationPage() {
  const resource = useAsyncResource(loadCalibrationHistory, []);
  const [metrics, setMetrics] = useState(DEFAULT_METRICS);
  const [policyVersion, setPolicyVersion] = useState("onboarding-policy-1.0.0");
  const [evidenceVersion, setEvidenceVersion] = useState("playtest-2026-08-15");
  const [selected, setSelected] = useState<CalibrationReport | null>(null);
  const [resultSource, setResultSource] = useState<DataSource>("live");
  const [resultReason, setResultReason] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const report = selected ?? resource.data?.data[0] ?? null;
  const promoted = Boolean(report?.promotion_id);
  const reviewed = Boolean(report && (report.review_id || report.reviewed_at || report.promotion_status !== "REVIEW_REQUIRED"));
  const approved = report?.promotion_status === "APPROVED";
  const lifecycleStatus = promoted ? "PROMOTED" : report?.promotion_status;

  async function compare() {
    setWorking(true); setError("");
    try {
      const response = await compareCalibration({ synthetic_metrics: Object.fromEntries(metrics.map((item) => [item.name, item.synthetic])), human_metrics: Object.fromEntries(metrics.map((item) => [item.name, item.human])), policy_version: policyVersion, evidence_version: evidenceVersion });
      setSelected(response.data); setResultSource(response.source); setResultReason(response.reason ?? "");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Calibration failed"); } finally { setWorking(false); }
  }

  async function review() {
    if (!report) return;
    setWorking(true); setError("");
    try { const response = await reviewCalibration(report); setSelected(response.data); setResultSource(response.source); setResultReason(response.reason ?? ""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Review failed"); } finally { setWorking(false); }
  }

  async function promote() {
    if (!report) return;
    setWorking(true); setError("");
    try { const response = await promoteCalibration(report); setSelected(response.data); setResultSource(response.source); setResultReason(response.reason ?? ""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Promotion failed"); } finally { setWorking(false); }
  }

  async function selectHistory(item: CalibrationReport) {
    setSelected(item); setWorking(true); setError("");
    try { const response = await loadCalibrationDetail(item.report_id, item); setSelected(response.data); setResultSource(response.source); setResultReason(response.reason ?? ""); } catch (reason) { setError(reason instanceof Error ? reason.message : "Calibration detail failed"); } finally { setWorking(false); }
  }

  if (resource.loading) return <LoadingState label="Loading calibration evidence" />;
  if (resource.error) return <ErrorState message={resource.error} retry={resource.reload} />;

  return (
    <div className="page calibration-page">
      <SourceNotice source={resultSource === "demo" ? resultSource : resource.data?.source ?? "live"} reason={resultSource === "demo" ? resultReason : resource.data?.reason} />
      <PageHeader title="Calibration" description="Compare synthetic hypotheses with consented human evidence, review the proposal, then register an approved immutable policy version as a deployable candidate." actions={<><button className="button primary" type="button" onClick={compare} disabled={working}><Scale size={15} />{working ? "Working…" : "Compare evidence"}</button><button className="button" type="button" onClick={review} disabled={working || !report || reviewed}><CheckCircle2 size={15} />{reviewed ? "Proposal reviewed" : "Approve proposal"}</button><button className="button" type="button" onClick={promote} disabled={working || !report || !approved || promoted}><Rocket size={15} />{promoted ? "Policy promoted" : "Promote policy"}</button></>} />
      {error ? <div className="error-banner" role="alert">{error}</div> : null}
      <div className="calibration-layout">
        <Panel title="Evidence contract" className="calibration-input">
          <label>Policy version<input value={policyVersion} onChange={(event) => setPolicyVersion(event.target.value)} /></label><label>Human evidence version<input value={evidenceVersion} onChange={(event) => setEvidenceVersion(event.target.value)} /></label>
          <div className="metric-input-table"><div className="metric-input-row header"><span>Metric</span><span>Synthetic</span><span>Human</span></div>{metrics.map((metric, index) => <div className="metric-input-row" key={metric.name}><input aria-label={`Metric ${index + 1} name`} value={metric.name} onChange={(event) => setMetrics((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))} /><input aria-label={`${metric.name} synthetic`} type="number" step="0.01" value={metric.synthetic} onChange={(event) => setMetrics((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, synthetic: Number(event.target.value) } : item))} /><input aria-label={`${metric.name} human`} type="number" step="0.01" value={metric.human} onChange={(event) => setMetrics((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, human: Number(event.target.value) } : item))} /></div>)}</div>
          <p className="constitutional-note"><ShieldAlert size={15} />Synthetic results remain hypotheses. Approval records a review decision; promotion registers a deployable immutable version, and runtime selection remains a separate explicit step.</p>
        </Panel>
        <Panel title="Metric comparison" meta={report && lifecycleStatus ? <Status value={lifecycleStatus} /> : undefined} className="calibration-results">
          {!report ? <EmptyState title="No calibration report" detail="Provide shared metrics and compare evidence." /> : <><div className="stat-strip"><Stat label="RMSE" value={report.root_mean_squared_error.toFixed(4)} /><Stat label="Metrics" value={report.metrics.length} /><Stat label="Human ground truth claimed" value={report.human_ground_truth_claimed ? "Yes" : "No"} /></div><div className="comparison-table"><div className="comparison-row header"><span>Metric</span><span>Synthetic</span><span>Human</span><span>Absolute error</span><span>Visual</span></div>{report.metrics.map((metric) => <div className="comparison-row" key={metric.metric}><strong>{metric.metric.replaceAll("_", " ")}</strong><span>{metric.synthetic_value.toFixed(3)}</span><span>{metric.human_value.toFixed(3)}</span><span className={metric.absolute_error > .1 ? "bad-text" : "safe"}>{metric.absolute_error.toFixed(3)}</span><span className="comparison-bars"><i style={{ width: `${Math.min(100, metric.synthetic_value * 100)}%` }} /><b style={{ width: `${Math.min(100, metric.human_value * 100)}%` }} /></span></div>)}</div></>}
        </Panel>
        <aside className="calibration-review">
          <Panel title="Review package">{report ? <DefinitionList items={[["Report", <span className="mono">{report.report_id}</span>], ["Synthetic policy", report.synthetic_policy_version], ["Evidence", report.evidence_version], ["Proposed policy", report.proposed_policy_version], ["Status", <Status value={lifecycleStatus ?? report.promotion_status} />], ["Reviewed by", report.reviewed_by ?? "Not reviewed"], ["Promoted by", report.promoted_by ?? "Not promoted"]]} /> : <EmptyState title="Awaiting comparison" detail="A proposed immutable policy version will appear here." />}</Panel>
          <Panel title="History" meta={<span>{resource.data?.data.length ?? 0} reports</span>}><div className="saved-personas">{resource.data?.data.map((item) => <button type="button" key={item.report_id} onClick={() => selectHistory(item)}><Scale size={15} /><span><strong>{item.evidence_version}</strong><small>RMSE {item.root_mean_squared_error} · {item.promotion_id ? "PROMOTED" : item.promotion_status}</small></span></button>)}</div></Panel>
        </aside>
      </div>
    </div>
  );
}
