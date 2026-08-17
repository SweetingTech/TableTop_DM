import { describe, expect, it, vi } from "vitest";
import { demoCalibrationReport } from "../core/demo/fixtures";
import {
  loadCalibrationDetail,
  promoteCalibration,
  reviewCalibration,
  unwrapCalibrationReport,
} from "../features/calibration/api";

function ok(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("calibration lifecycle API", () => {
  it("accepts bare and wrapped detail report responses", async () => {
    const promoted = { ...demoCalibrationReport, promotion_id: "promotion-1" };
    expect(unwrapCalibrationReport(promoted)).toBe(promoted);
    expect(unwrapCalibrationReport({ report: promoted })).toBe(promoted);

    vi.mocked(fetch).mockResolvedValueOnce(ok({ report: promoted }));
    const detail = await loadCalibrationDetail(promoted.report_id, demoCalibrationReport);
    expect(detail.source).toBe("live");
    expect(detail.data.promotion_id).toBe("promotion-1");
  });

  it("reviews before calling the separate promotion endpoint", async () => {
    const reviewed = {
      ...demoCalibrationReport,
      promotion_status: "APPROVED",
      review_id: "review-1",
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(ok({ review: { review_id: "review-1" }, report: reviewed }))
      .mockResolvedValueOnce(
        ok({
          promotion: { promotion_id: "promotion-1" },
          report: { ...reviewed, promotion_id: "promotion-1" },
        }),
      );

    const review = await reviewCalibration(demoCalibrationReport);
    const promotion = await promoteCalibration(review.data);
    expect(review.data.review_id).toBe("review-1");
    expect(promotion.data.promotion_id).toBe("promotion-1");
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      `/api/v2/calibration/${demoCalibrationReport.report_id}/review`,
    );
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe(
      `/api/v2/calibration/${demoCalibrationReport.report_id}/promote`,
    );
  });
});
