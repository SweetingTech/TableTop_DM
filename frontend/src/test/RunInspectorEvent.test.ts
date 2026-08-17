import { describe, expect, it } from "vitest";
import type { EventRecord } from "../core/api/types";
import { eventActor, eventSummary } from "../features/run-inspector/eventPresentation";

describe("run inspector event presentation", () => {
  it("derives useful text from a raw EventEnvelopeV2 payload", () => {
    const event: EventRecord = {
      event_id: "event-1",
      event_type: "experiments.scenario.apply",
      actor_id: "actor-42",
      payload: { scenario_id: "market-tax", status: "COMPLETED" },
      created_at: "2026-08-17T12:00:00Z",
    };
    expect(eventSummary(event)).toContain("Apply");
    expect(eventSummary(event)).toContain("Market tax");
    expect(eventActor(event)).toBe("actor-42");
  });

  it("prefers explicit presentation fields when available", () => {
    const event: EventRecord = {
      event_id: "event-2",
      event_type: "tabletop.move",
      actor_name: "Aster",
      summary: "Aster moved north.",
      created_at: "2026-08-17T12:00:00Z",
    };
    expect(eventSummary(event)).toBe("Aster moved north.");
    expect(eventActor(event)).toBe("Aster");
  });
});
