import { apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { CalibrationReport, Sourced } from "../../core/api/types";
import { demoCalibrationReport } from "../../core/demo/fixtures";

type CalibrationEnvelope = CalibrationReport | { report: CalibrationReport };

export function unwrapCalibrationReport(payload: CalibrationEnvelope): CalibrationReport {
  return "report" in payload ? payload.report : payload;
}

export async function loadCalibrationHistory(): Promise<Sourced<CalibrationReport[]>> {
  return withDemoFallback(
    async () =>
      unpackItems(
        await apiRequest<CalibrationReport[] | { items?: CalibrationReport[] }>(
          "/calibration/history",
        ),
      ),
    () => [demoCalibrationReport],
    "Calibration history",
  );
}

export async function loadCalibrationDetail(
  reportId: string,
  summary: CalibrationReport,
): Promise<Sourced<CalibrationReport>> {
  return withDemoFallback(
    async () =>
      unwrapCalibrationReport(
        await apiRequest<CalibrationEnvelope>(`/calibration/${reportId}`),
      ),
    () => summary,
    "Calibration detail",
  );
}

export async function compareCalibration(input: {
  synthetic_metrics: Record<string, number>;
  human_metrics: Record<string, number>;
  policy_version: string;
  evidence_version: string;
}): Promise<Sourced<CalibrationReport>> {
  return withDemoFallback(
    () =>
      apiRequest<CalibrationReport>("/calibration/compare", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    () => demoCalibrationReport,
    "Calibration comparison",
  );
}

export async function reviewCalibration(
  report: CalibrationReport,
): Promise<Sourced<CalibrationReport>> {
  return withDemoFallback(
    async () =>
      unwrapCalibrationReport(
        await apiRequest<CalibrationEnvelope>(
          `/calibration/${report.report_id}/review`,
          {
            method: "POST",
            body: JSON.stringify({
              reviewer: "Local operator",
              decision: "APPROVED",
              rationale: "Approved for explicit policy promotion review.",
            }),
          },
        ),
      ),
    () => ({
      ...report,
      promotion_status: "APPROVED",
      review_id: `review-${report.report_id}`,
      reviewed_by: "Local operator",
      reviewed_at: new Date(0).toISOString(),
      approved_by: "Local operator",
      approved_at: new Date(0).toISOString(),
    }),
    "Calibration review",
  );
}

export async function promoteCalibration(
  report: CalibrationReport,
): Promise<Sourced<CalibrationReport>> {
  return withDemoFallback(
    async () =>
      unwrapCalibrationReport(
        await apiRequest<CalibrationEnvelope>(
          `/calibration/${report.report_id}/promote`,
          {
            method: "POST",
            body: JSON.stringify({ promoted_by: "Local operator" }),
          },
        ),
      ),
    () => ({
      ...report,
      promotion_id: `promotion-${report.report_id}`,
      promoted_by: "Local operator",
      promoted_at: new Date(0).toISOString(),
    }),
    "Calibration promotion",
  );
}
