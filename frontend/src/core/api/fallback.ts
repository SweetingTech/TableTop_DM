import { endpointUnavailable } from "./client";
import type { Sourced } from "./types";

export async function withDemoFallback<T>(
  request: () => Promise<T>,
  fixture: () => T,
  label: string,
): Promise<Sourced<T>> {
  try {
    return { data: await request(), source: "live" };
  } catch (error) {
    if (!endpointUnavailable(error)) throw error;
    return {
      data: fixture(),
      source: "demo",
      reason: `${label} endpoint unavailable; deterministic demo data is shown.`,
    };
  }
}
