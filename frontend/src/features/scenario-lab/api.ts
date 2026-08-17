import { ApiError, apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { CohortReport, JobSummary, ScenarioSummary, Sourced } from "../../core/api/types";
import { demoCohortReport, demoScenarios } from "../../core/demo/fixtures";

export type ScenarioLaunch = { job: JobSummary | null; report: CohortReport | null };

export async function loadScenarios(): Promise<Sourced<ScenarioSummary[]>> {
  return withDemoFallback(
    async () => unpackItems(await apiRequest<ScenarioSummary[] | { items?: ScenarioSummary[] }>("/scenarios")),
    () => demoScenarios,
    "Scenario definitions",
  );
}

export async function launchScenario(scenario: ScenarioSummary, cohortSize: number, seeds: number[]): Promise<Sourced<ScenarioLaunch>> {
  return withDemoFallback(
    async () => {
      let payload: CohortReport | JobSummary | { job?: JobSummary; report?: CohortReport };
      try {
        payload = await apiRequest(`/scenarios/${encodeURIComponent(scenario.scenario_id)}/run`, { method: "POST", body: JSON.stringify({ cohort_size: cohortSize, seeds }) });
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404 || scenario.scenario_id !== "tabletop.player-onboarding") throw error;
        payload = await apiRequest<CohortReport>("/experiments/onboarding/run", { method: "POST", body: JSON.stringify({ cohort_size: cohortSize, seeds, include_trials: 20 }) });
      }
      if ("scenario_id" in payload) return { job: null, report: payload as CohortReport };
      if ("job_id" in payload) return { job: payload as JobSummary, report: (payload as JobSummary).report ?? null };
      return { job: payload.job ?? null, report: payload.report ?? null };
    },
    () => ({ job: { job_id: "job-onboarding-demo", kind: "SCENARIO", status: "COMPLETED", progress: 1, completed: cohortSize * seeds.length, total: cohortSize * seeds.length, report: demoCohortReport(cohortSize, seeds) }, report: demoCohortReport(cohortSize, seeds) }),
    "Scenario run",
  );
}

export async function loadJob(jobId: string): Promise<JobSummary> {
  return apiRequest<JobSummary>(`/jobs/${jobId}`);
}

export async function cancelJob(jobId: string): Promise<JobSummary> {
  return apiRequest<JobSummary>(`/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function retryJob(jobId: string): Promise<JobSummary> {
  return apiRequest<JobSummary>(`/jobs/${jobId}/retry`, { method: "POST" });
}
