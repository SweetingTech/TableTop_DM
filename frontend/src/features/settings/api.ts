import { apiRequest } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { KernelMeta, Sourced, TelemetrySettings } from "../../core/api/types";
import { demoMeta, demoTelemetry } from "../../core/demo/fixtures";

export type SettingsData = { meta: KernelMeta; telemetry: TelemetrySettings };

export async function loadSettings(): Promise<Sourced<SettingsData>> {
  return withDemoFallback(
    async () => {
      const [meta, telemetry] = await Promise.all([apiRequest<KernelMeta>("/meta"), apiRequest<TelemetrySettings>("/telemetry")]);
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

export async function verifyAccess(): Promise<KernelMeta> {
  return apiRequest<KernelMeta>("/meta");
}
