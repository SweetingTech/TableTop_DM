import { apiRequest } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { KernelMeta, Sourced, TelemetrySettings } from "../../core/api/types";
import { demoMeta, demoTelemetry } from "../../core/demo/fixtures";

export type SettingsData = { meta: KernelMeta; telemetry: TelemetrySettings };

export async function loadSettings(includeTelemetry = true): Promise<Sourced<SettingsData>> {
  return withDemoFallback(
    async () => {
      const meta = await apiRequest<KernelMeta>("/meta");
      const telemetry = includeTelemetry ? await apiRequest<TelemetrySettings>("/telemetry") : demoTelemetry;
      return { meta, telemetry };
    },
    () => ({ meta: demoMeta, telemetry: demoTelemetry }),
    "Settings",
  );
}

export async function updateTelemetry(enabled: boolean): Promise<Sourced<TelemetrySettings>> {
  return withDemoFallback(
    () => apiRequest<TelemetrySettings>("/telemetry", { method: "PUT", body: JSON.stringify({ enabled }) }),
    () => ({ human_telemetry_enabled: enabled, local_only: true }),
    "Telemetry settings",
  );
}
