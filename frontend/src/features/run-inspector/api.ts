import { apiRequest, endpointUnavailable, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { JobSummary, Sourced, Trial } from "../../core/api/types";
import { demoJobs, demoTrial } from "../../core/demo/fixtures";

export type TrialComparison = { left_trial_id: string; right_trial_id: string; metric_deltas: Record<string, number>; same_canonical_origin: boolean };

export async function loadRuns(): Promise<Sourced<JobSummary[]>> {
  return withDemoFallback(
    async () => unpackItems(await apiRequest<JobSummary[] | { items?: JobSummary[] }>("/jobs?kind=SCENARIO")),
    () => demoJobs,
    "Run history",
  );
}

export async function loadTrialDetail(trialId: string, summary?: Trial): Promise<Sourced<Trial>> {
  try {
    return { data: await apiRequest<Trial>(`/trials/${trialId}`), source: "live" };
  } catch (error) {
    if (!endpointUnavailable(error)) throw error;
    if (summary) return { data: summary, source: "live", reason: "The detail endpoint is unavailable; the live normalized trial summary is shown." };
    return { data: demoTrial(0, 101), source: "demo", reason: "Trial detail endpoint unavailable; deterministic demo data is shown." };
  }
}

export async function compareTrials(left: Trial, right: Trial): Promise<Sourced<TrialComparison>> {
  return withDemoFallback(
    () => apiRequest<TrialComparison>("/trials/compare", { method: "POST", body: JSON.stringify({ left_trial_id: left.trial_id, right_trial_id: right.trial_id }) }),
    () => {
      const keys = [...new Set([...Object.keys(left.metrics), ...Object.keys(right.metrics)])];
      return { left_trial_id: left.trial_id, right_trial_id: right.trial_id, metric_deltas: Object.fromEntries(keys.flatMap((key) => typeof left.metrics[key] === "number" && typeof right.metrics[key] === "number" ? [[key, Number(right.metrics[key]) - Number(left.metrics[key])]] : [])), same_canonical_origin: left.canonical_hash_before === right.canonical_hash_before };
    },
    "Trial comparison",
  );
}
