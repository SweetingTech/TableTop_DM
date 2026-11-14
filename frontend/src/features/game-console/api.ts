import { apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { BranchSummary, EntitySummary, EventRecord, GameState, PerceivedScene, RunSummary, Sourced, ViewpointSummary } from "../../core/api/types";
import { DEMO_BRANCH_ID, DEMO_RUN_ID, demoGameState } from "../../core/demo/fixtures";
import { waitForScene, type SceneRefreshCursor } from "./sceneRefresh";

export type ControlMode = "HUMAN" | "AUTONOMOUS" | "PAUSED";
export type ControllerState = {
  epoch: number; mode: ControlMode; step: number; max_steps: number;
  last_error: string | null; next_due: string;
};
export type ControllerScope = { world: string; branch: string; run: string; entity: string };
function controlPath(scope: ControllerScope): string {
  return `/worlds/${encodeURIComponent(scope.world)}/branches/${encodeURIComponent(scope.branch)}/entities/${encodeURIComponent(scope.entity)}/control`;
}
export async function loadController(scope: ControllerScope, signal?: AbortSignal) {
  return apiRequest<{ control: ControllerState | null; disconnect_policy: string }>(
    controlPath(scope) + `?run_id=${encodeURIComponent(scope.run)}`, { signal, cache: "no-store" });
}
export async function handoffController(scope: ControllerScope, mode: ControlMode, epoch: number,
                                      maxSteps: number, idempotencyKey: string) {
  return apiRequest<{ state: ControllerState }>(controlPath(scope), { method: "POST",
    body: JSON.stringify({ run_id: scope.run, mode, expected_epoch: epoch,
      max_steps: maxSteps, interval_ms: 1000, idempotency_key: idempotencyKey }) });
}

function normalizeEvent(raw: Record<string, unknown>): EventRecord {
  const payload = raw.payload && typeof raw.payload === "object" ? raw.payload as Record<string, unknown> : {};
  return {
    event_id: String(raw.event_id ?? raw.id ?? "event-unidentified"),
    source_event_id: raw.source_event_id ? String(raw.source_event_id) : undefined,
    event_type: String(raw.event_type ?? raw.type ?? "kernel.event"),
    actor_name: raw.actor_name ? String(raw.actor_name) : undefined,
    summary: String(raw.summary ?? payload.summary ?? payload.message ?? raw.event_type ?? "Event recorded"),
    created_at: String(raw.created_at ?? new Date(0).toISOString()),
    sequence: typeof raw.sequence === "number" ? raw.sequence : undefined,
    domain_tags: Array.isArray(raw.domain_tags) ? raw.domain_tags.map(String) : [],
    correlation_id: raw.correlation_id ? String(raw.correlation_id) : undefined,
    causation_id: raw.causation_id ? String(raw.causation_id) : null,
  };
}

export async function loadGameState(worldId: string, requestedViewpoint = "", cursor?: SceneRefreshCursor, signal?: AbortSignal): Promise<Sourced<GameState>> {
  if (!worldId) return { data: demoGameState, source: "demo", reason: "No live world is selected; deterministic demo data is shown." };
  const load = async (): Promise<GameState> => {
      const [viewpointsPayload, runsPayload, branchesPayload] = await Promise.all([
        apiRequest<{ items?: ViewpointSummary[] }>(`/worlds/${worldId}/viewpoints`, { signal }),
        apiRequest<RunSummary[] | { items?: RunSummary[] }>(`/runs?world_id=${encodeURIComponent(worldId)}`, { signal }),
        apiRequest<BranchSummary[] | { items?: BranchSummary[] }>(`/branches?world_id=${encodeURIComponent(worldId)}`, { signal }),
      ]);
      const runs = unpackItems(runsPayload);
      const branches = unpackItems(branchesPayload);
      const viewpoints = unpackItems(viewpointsPayload);
      const branch = branches.find((item) => item.kind === "CANONICAL") ?? branches[0] ?? null;
      const observer = viewpoints.find((item) => item.entity_id === requestedViewpoint) ?? viewpoints[0];
      if (!branch || !observer) {
        if (cursor) throw new Error("The assigned character or branch is no longer available.");
        return {
          run: runs.find((run) => run.status === "RUNNING" || run.status === "ACTIVE") ?? runs[0] ?? null,
          branch,
          entities: [],
          events: [],
          viewpoints,
          turn: 0,
          interaction_status: "ACTIVE",
        };
      }
      if (cursor && (cursor.world_id !== worldId || cursor.branch_id !== branch.branch_id
        || cursor.observer_entity_id !== observer.entity_id)) {
        throw new Error("The assigned character or branch changed while refreshing.");
      }
      const path = `/worlds/${encodeURIComponent(worldId)}/branches/${encodeURIComponent(branch.branch_id)}/entities/${encodeURIComponent(observer.entity_id)}/scene`;
      const read = (readSignal?: AbortSignal) => apiRequest<PerceivedScene>(
        path + (cursor ? `?after_event_id=${encodeURIComponent(cursor.event_id)}` : ""), { signal: readSignal, cache: "no-store" },
      );
      const scene = cursor ? await waitForScene(read, cursor, signal) : await read(signal);
      const entities: EntitySummary[] = scene.perceived_entities.map((entity) => ({
        entity_id: entity.entity_id,
        world_id: worldId,
        branch_id: branch.branch_id,
        name: entity.name ?? (entity.detail_level === "PRESENCE" ? "Distant figure" : "Unknown person"),
        entity_type: entity.apparent_type ?? "UNKNOWN",
        location: entity.position ? `(${entity.position.x}, ${entity.position.y}) · ${entity.position.zone_id}` : "Uncertain",
        health: entity.health ?? undefined,
        max_health: entity.max_health ?? undefined,
        status: entity.status ?? undefined,
        public_state: entity.position ?? undefined,
        knowledge_state: entity.knowledge_state,
        detail_level: entity.detail_level,
        position_confidence: entity.position_confidence,
      }));
      return {
        run: runs.find((run) => run.status === "RUNNING" || run.status === "ACTIVE") ?? runs[0] ?? null,
        branch,
        entities,
        events: scene.recent_observations.map((observation) => normalizeEvent({
          event_id: observation.observation_id,
          event_type: observation.event_type,
          summary: observation.summary,
          created_at: observation.observed_at,
          source_event_id: observation.source_event_id,
        })),
        viewpoints,
        observer_entity_id: observer.entity_id,
        projection_version: scene.projection_version,
        turn: 0,
        interaction_status: "ACTIVE",
      };
    };
  // An accepted live command must never become a demo receipt or a demo scene on failure.
  if (cursor) return { data: await load(), source: "live" };
  return withDemoFallback(load, () => {
    if (signal?.aborted) throw new DOMException("Scene refresh cancelled", "AbortError");
    return demoGameState;
  }, "Game console");
}

export type CommandAcknowledgement = { event_id: string; scene_refresh: SceneRefreshCursor | null };

export async function proposeCommand(
  worldId: string,
  command: string,
  state: GameState,
  embodiedEntityId: string | undefined,
  controlEpoch?: number,
): Promise<Sourced<CommandAcknowledgement>> {
  const parsed = parseCommand(command, state);
  const result = await apiRequest<{
    result: { accepted: boolean }; event: { event_id: string }; scene_refresh?: SceneRefreshCursor | null;
  }>("/commands", {
        method: "POST",
        body: JSON.stringify({
          command_type: parsed.commandType,
          world_id: worldId,
          branch_id: state.branch?.branch_id ?? DEMO_BRANCH_ID,
          run_id: state.run?.run_id ?? DEMO_RUN_ID,
          embodied_entity_id: embodiedEntityId,
          parameters: parsed.parameters,
          seed: parsed.seed,
          idempotency_key: `console:${crypto.randomUUID()}`,
          control_epoch: controlEpoch,
        }),
      });
  if (!result.result.accepted) throw new Error("The action was not accepted.");
  return { data: { event_id: result.event.event_id, scene_refresh: result.scene_refresh ?? null }, source: "live" };
}

type ParsedCommand = {
  commandType: string;
  parameters: Record<string, unknown>;
  seed?: number;
};

function resolveEntity(reference: string, state: GameState): string {
  const folded = reference.toLocaleLowerCase();
  const match = state.entities.find(
    (entity) =>
      entity.entity_id === reference || entity.name.toLocaleLowerCase() === folded,
  );
  if (!match) throw new Error(`Unknown target entity: ${reference}`);
  return match.entity_id;
}

function positiveInteger(raw: string | undefined, label: string): number {
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) throw new Error(`${label} must be a non-negative integer`);
  return value;
}

function stableSeed(text: string): number {
  let value = 2166136261;
  for (const character of text) {
    value ^= character.charCodeAt(0);
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

export function parseCommand(command: string, state: GameState): ParsedCommand {
  const text = command.trim();
  if (!text.startsWith("/")) {
    return { commandType: "tabletop.dialogue.speak", parameters: { text, volume: "NORMAL", language: "common" } };
  }
  const [verb = "", ...parts] = text.slice(1).trim().split(/\s+/);
  switch (verb.toLocaleLowerCase()) {
    case "move": {
      const directions: Record<string, [number, number]> = {
        north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0],
      };
      const direction = directions[(parts[0] ?? "").toLocaleLowerCase()];
      const [dx, dy] = direction ?? [Number(parts[0]), Number(parts[1])];
      if (![dx, dy].every((value) => Number.isInteger(value) && Math.abs(value) <= 1) || (dx === 0 && dy === 0)) {
        throw new Error("Use /move north|south|east|west or /move <dx> <dy> with -1..1");
      }
      return { commandType: "tabletop.spatial.move", parameters: { dx, dy } };
    }
    case "attack": {
      if (!parts[0]) throw new Error("Use /attack <entity name or id>");
      return {
        commandType: "tabletop.combat.attack",
        parameters: { target_id: resolveEntity(parts.join(" "), state) },
        seed: stableSeed(`${state.run?.run_id ?? "run"}:${text}`),
      };
    }
    case "cast": {
      if (parts.length < 5) {
        throw new Error("Use /cast <target> <damage|heal|condition> <power> <mana> <spell>");
      }
      const [target, effect, power, mana, ...spell] = parts;
      const normalizedEffect = effect.toUpperCase();
      if (!["DAMAGE", "HEAL", "CONDITION"].includes(normalizedEffect)) {
        throw new Error("Cast effect must be damage, heal, or condition");
      }
      const parameters: Record<string, unknown> = {
        target_id: resolveEntity(target, state), spell: spell.join(" "),
        effect: normalizedEffect, power: positiveInteger(power, "Power"),
        mana_cost: positiveInteger(mana, "Mana"),
      };
      if (normalizedEffect === "CONDITION") parameters.condition = spell.join(" ");
      return { commandType: "tabletop.magic.cast", parameters };
    }
    default:
      return { commandType: "tabletop.console.submit", parameters: { text } };
  }
}
