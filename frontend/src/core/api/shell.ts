import { apiRequest, unpackItems } from "./client";
import { withDemoFallback } from "./fallback";
import type { KernelMeta, Sourced, WorldSummary } from "./types";
import { demoMeta, demoWorlds } from "../demo/fixtures";

export type ShellBootstrap = {
  meta: KernelMeta;
  worlds: WorldSummary[];
};

export async function loadShellBootstrap(): Promise<Sourced<ShellBootstrap>> {
  return withDemoFallback(
    async () => {
      const [meta, worldsPayload] = await Promise.all([
        apiRequest<KernelMeta>("/meta"),
        apiRequest<WorldSummary[] | { items?: WorldSummary[] }>("/worlds"),
      ]);
      return { meta, worlds: unpackItems(worldsPayload) };
    },
    () => ({ meta: demoMeta, worlds: demoWorlds }),
    "Kernel bootstrap",
  );
}
