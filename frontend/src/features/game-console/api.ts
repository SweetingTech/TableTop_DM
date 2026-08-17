import { apiRequest, unpackItems } from "../../core/api/client";
import { withDemoFallback } from "../../core/api/fallback";
import type { BranchSummary, EntitySummary, EventRecord, GameState, RunSummary, Sourced } from "../../core/api/types";
import { DEMO_BRANCH_ID, DEMO_RUN_ID, demoGameState } from "../../core/demo/fixtures";

function normalizeEvent(raw: Record<string, unknown>): EventRecord {
  const payload = raw.payload && typeof raw.payload === "object" ? raw.payload as Record<string, unknown> : {};
  return {
    event_id: String(raw.event_id ?? raw.id ?? "event-unidentified"),
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

export async function loadGameState(worldId: string): Promise<Sourced<GameState>> {
  if (!worldId) return { data: demoGameState, source: "demo", reason: "No live world is selected; deterministic demo data is shown." };
  return withDemoFallback(
    async () => {
      const [entitiesPayload, runsPayload, branchesPayload, eventsPayload] = await Promise.all([
        apiRequest<EntitySummary[] | { items?: EntitySummary[] }>(`/worlds/${worldId}/entities`),
        apiRequest<RunSummary[] | { items?: RunSummary[] }>(`/runs?world_id=${encodeURIComponent(worldId)}`),
        apiRequest<BranchSummary[] | { items?: BranchSummary[] }>(`/branches?world_id=${encodeURIComponent(worldId)}`),
        apiRequest<Record<string, unknown>[] | { items?: Record<string, unknown>[] }>(`/events?world_id=${encodeURIComponent(worldId)}&limit=80`),
      ]);
      const runs = unpackItems(runsPayload);
      const branches = unpackItems(branchesPayload);
      return {
        run: runs.find((run) => run.status === "RUNNING" || run.status === "ACTIVE") ?? runs[0] ?? null,
        branch: branches.find((branch) => branch.kind === "CANONICAL") ?? branches[0] ?? null,
        entities: unpackItems(entitiesPayload),
        events: unpackItems(eventsPayload).map(normalizeEvent),
        turn: 0,
        interaction_status: "ACTIVE",
      };
    },
    () => demoGameState,
    "Game console",
  );
}

export async function proposeCommand(
  worldId: string,
  command: string,
  state: GameState,
  embodiedEntityId: string | undefined,
): Promise<Sourced<EventRecord>> {
  const parsed = parseCommand(command, state);
  return withDemoFallback(
    async () => {
      const result = await apiRequest<Record<string, unknown>>("/commands", {
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
        }),
      });
      return normalizeEvent((result.event as Record<string, unknown> | undefined) ?? result);
    },
    () => ({
      event_id: `demo-command-${command.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 32)}`,
      event_type: command.startsWith("/") ? "tabletop.command.proposed" : "tabletop.dialogue.spoken",
      actor_name: "Local operator",
      summary: command.startsWith("/") ? `Proposed ${command}.` : command,
      created_at: "2026-08-17T14:34:00Z",
      domain_tags: ["deterministic-demo"],
    }),
    "Command proposal",
  );
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
    return { commandType: "tabletop.console.submit", parameters: { text } };
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
