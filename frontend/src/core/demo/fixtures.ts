import type {
  ActorSummary,
  Belief,
  BranchSummary,
  CalibrationReport,
  CohortMember,
  CohortReport,
  EntitySummary,
  EventRecord,
  GameState,
  JobSummary,
  KernelMeta,
  Memory,
  Observation,
  PersonaBlueprint,
  PersonaDimension,
  PersonaSchema,
  PopulationDefinition,
  RunSummary,
  ScenarioSummary,
  SnapshotSummary,
  TelemetrySettings,
  Trial,
  WorldSummary,
} from "../api/types";

export const DEMO_WORLD_ID = "11111111-1111-4111-8111-111111111111";
export const DEMO_BRANCH_ID = "22222222-2222-4222-8222-222222222222";
export const DEMO_RUN_ID = "33333333-3333-4333-8333-333333333333";

export const demoMeta: KernelMeta = {
  contract_version: "2.0.0",
  kernel: "tabletop-simulation-kernel",
  persona_schema_version: "2.0.0",
  persona_dimensions: 80,
  telemetry_enabled: false,
  migrations_from_v1_supported: false,
};

export const demoWorlds: WorldSummary[] = [
  {
    world_id: DEMO_WORLD_ID,
    name: "Harborport 1831",
    status: "ACTIVE",
    current_run_id: DEMO_RUN_ID,
    updated_at: "2026-08-17T14:32:00Z",
  },
  {
    world_id: "11111111-1111-4111-8111-111111111112",
    name: "Silverholt 1742",
    status: "IDLE",
    updated_at: "2026-08-16T20:10:00Z",
  },
];

export const demoActors: ActorSummary[] = [
  {
    actor_id: "44444444-4444-4444-8444-444444444441",
    display_name: "Douglas · GM",
    kind: "HUMAN",
    roles: ["GM", "OBSERVER"],
    capabilities: ["world.read", "entity.control", "action.propose", "action.commit", "run.branch"],
  },
  {
    actor_id: "44444444-4444-4444-8444-444444444442",
    display_name: "Dockmaster Vale",
    kind: "AGENT",
    roles: ["NPC"],
    capabilities: ["world.read", "entity.control", "action.propose"],
  },
  {
    actor_id: "44444444-4444-4444-8444-444444444443",
    display_name: "Ledger Verifier",
    kind: "SYSTEM",
    roles: ["VERIFIER"],
    capabilities: ["world.read", "metric.evaluate"],
  },
];

export const demoEntities: EntitySummary[] = [
  {
    entity_id: "55555555-5555-4555-8555-555555555551",
    name: "Brigid Shaw",
    entity_type: "PC",
    controller_actor_id: demoActors[0].actor_id,
    location: "Shipwright Market",
    health: 31,
    max_health: 36,
    status: "ACTIVE",
    public_state: { x: 3, y: 2 },
  },
  {
    entity_id: "55555555-5555-4555-8555-555555555552",
    name: "Dockmaster Vale",
    entity_type: "NPC",
    controller_actor_id: demoActors[1].actor_id,
    location: "Harbor Office",
    health: 18,
    max_health: 18,
    status: "ACTIVE",
    public_state: { x: 4, y: 1 },
  },
  {
    entity_id: "55555555-5555-4555-8555-555555555553",
    name: "Sable",
    entity_type: "NPC",
    location: "Market Courtyard",
    health: 14,
    max_health: 14,
    status: "ACTIVE",
    public_state: { x: 2, y: 3 },
  },
];

export const demoRuns: RunSummary[] = [
  {
    run_id: DEMO_RUN_ID,
    world_id: DEMO_WORLD_ID,
    name: "Market Day",
    kind: "LIVE",
    status: "RUNNING",
    started_at: "2026-08-17T13:22:00Z",
    duration: "01:10:08",
  },
  {
    run_id: "33333333-3333-4333-8333-333333333334",
    world_id: DEMO_WORLD_ID,
    name: "Player Onboarding",
    kind: "EVALUATION",
    status: "COMPLETED",
    started_at: "2026-08-17T10:42:00Z",
    duration: "00:14:37",
  },
];

export const demoSnapshots: SnapshotSummary[] = [
  { snapshot_id: "snap-map-42", name: "Market Day · opening", state_hash: "7f3c9a2b", event_sequence: 812, created_at: "2026-08-17T13:22:00Z" },
  { snapshot_id: "snap-dawn-42", name: "Day 42 · dawn", state_hash: "a1d4f6e8", event_sequence: 764, created_at: "2026-08-17T06:00:00Z" },
];

export const demoBranches: BranchSummary[] = [
  { branch_id: DEMO_BRANCH_ID, name: "Canonical", kind: "CANONICAL", status: "ACTIVE", base_snapshot_id: "snap-map-42" },
  { branch_id: "22222222-2222-4222-8222-222222222223", name: "Tax counterfactual", kind: "TRIAL", status: "SEALED", base_snapshot_id: "snap-map-42" },
];

export const demoEvents: EventRecord[] = [
  { event_id: "evt-0813", event_type: "tabletop.dialogue.spoken", actor_name: "Dockmaster Vale", summary: "Warned Brigid that the east pier closes at dusk.", created_at: "2026-08-17T14:27:12Z", sequence: 813, domain_tags: ["dialogue", "audible"] },
  { event_id: "evt-0814", event_type: "tabletop.trade.completed", actor_name: "Brigid Shaw", summary: "Purchased a harbor permit for 12 silver.", created_at: "2026-08-17T14:28:43Z", sequence: 814, domain_tags: ["economy"] },
  { event_id: "evt-0815", event_type: "cognition.belief.updated", actor_name: "Sable", summary: "Raised confidence that the watch is distracted.", created_at: "2026-08-17T14:29:09Z", sequence: 815, domain_tags: ["belief"] },
  { event_id: "evt-0816", event_type: "tabletop.movement.completed", actor_name: "Brigid Shaw", summary: "Moved from the harbor office to Shipwright Market.", created_at: "2026-08-17T14:31:55Z", sequence: 816, domain_tags: ["spatial"] },
];

export const demoGameState: GameState = {
  run: demoRuns[0],
  branch: demoBranches[0],
  entities: demoEntities,
  events: demoEvents,
  turn: 143,
  interaction_status: "IN_PROGRESS",
};

const dimension = (
  name: string,
  pack: PersonaDimension["pack"],
  values: string[],
  depends_on: Record<string, unknown[]> = {},
): PersonaDimension => ({ name, pack, kind: "enum", values, default: values[0], depends_on });

export const demoPersonaSchema: PersonaSchema = {
  version: "2.0.0",
  dimensions: [
    dimension("decision_style", "core", ["DELIBERATIVE", "INTUITIVE", "SOCIAL"]),
    dimension("risk_tolerance", "core", ["LOW", "MEDIUM", "HIGH"]),
    dimension("authority_trust", "core", ["LOW", "MEDIUM", "HIGH"]),
    dimension("curiosity", "core", ["LOW", "MEDIUM", "HIGH"]),
    dimension("communication_style", "core", ["DIRECT", "DIPLOMATIC", "RESERVED"]),
    dimension("region", "world", ["HARBORPORT", "SILVERHOLT", "NEW_BRIAR"]),
    dimension("social_class", "world", ["POOR", "WORKING", "COMFORTABLE", "ELITE"]),
    dimension("occupation_sector", "world", ["MERCHANT", "LABORER", "GUARD", "SAILOR", "SCHOLAR"], { social_class: ["WORKING", "COMFORTABLE", "ELITE"] }),
    dimension("rules_familiarity", "tabletop", ["NOVICE", "INTERMEDIATE", "EXPERT"]),
    dimension("play_preference", "tabletop", ["EXPLORATION", "COMBAT", "ROLEPLAY", "BALANCED"]),
    dimension("reading_load", "accessibility", ["LOW", "MEDIUM", "HIGH"]),
    dimension("interface_preference", "accessibility", ["KEYBOARD", "POINTER", "MIXED"]),
  ],
};

export function demoPersona(seed = 4815162342): PersonaBlueprint {
  const pick = <T,>(items: T[], offset: number): T => items[Math.abs(seed + offset) % items.length];
  const dimensions: Record<string, unknown> = {};
  demoPersonaSchema.dimensions.forEach((spec, index) => {
    dimensions[spec.name] = pick(spec.values ?? [spec.default], index * 17);
  });
  return {
    persona_id: `per-demo-${String(Math.abs(seed)).padStart(10, "0")}`,
    schema_version: demoPersonaSchema.version,
    seed,
    generator_version: "persona-gen-demo-1.0.0",
    source: "synthetic",
    dimensions,
    derived_traits: { planning_depth: dimensions.decision_style === "DELIBERATIVE" ? 3 : 1, impulse_noise: dimensions.risk_tolerance === "HIGH" ? 0.28 : 0.1 },
    provenance: Object.fromEntries(Object.keys(dimensions).map((name) => [name, { source: "deterministic_demo", seed }])),
    validation: { status: "valid", ruleset_version: "constraints-demo-1.0.0", errors: [] },
  };
}

export const demoPopulations: PopulationDefinition[] = [
  {
    population_id: "pop-harborport",
    world_id: DEMO_WORLD_ID,
    name: "Harborport Citizens",
    size: 1114,
    status: "READY",
    schema_version: "2.0.0",
    seed: 1831,
    materialized: 114,
    active: 18,
    dimensions: {
      occupation_sector: { MERCHANT: 184, LABORER: 386, GUARD: 92, SAILOR: 284, SCHOLAR: 168 },
      risk_tolerance: { LOW: 312, MEDIUM: 612, HIGH: 190 },
    },
  },
];

export function demoCohort(size = 8): CohortMember[] {
  return Array.from({ length: size }, (_, index) => {
    const persona = demoPersona(183100 + index);
    return { persona_id: persona.persona_id, seed: persona.seed, dimensions: persona.dimensions };
  });
}

export const demoScenarios: ScenarioSummary[] = [
  {
    scenario_id: "tabletop.player-onboarding",
    version: "1.0.0",
    name: "Player Onboarding",
    description: "Measures whether simulated players understand the opening task and reach a valid first decision.",
    cohort_size: 100,
    seeds: [101, 202, 303],
    status: "READY",
    verifier_versions: ["onboarding-verifier-1.0.0", "branch-isolation-1.0.0"],
  },
  {
    scenario_id: "tabletop.market-tax",
    version: "0.3.0",
    name: "Market Tax Increase",
    description: "Compares thirty-day compliance and displacement across occupation and wealth strata.",
    cohort_size: 60,
    seeds: [101, 202, 303],
    status: "DRAFT",
    verifier_versions: ["economy-verifier-0.3.0"],
  },
];

const observations: Observation[] = [
  { observation_id: "obs-demo-1", summary: "The guide identified the command input and offered a first task.", confidence: 0.96, source_event_id: "trial-event-1" },
  { observation_id: "obs-demo-2", summary: "The task completion state changed after a valid action.", confidence: 1, source_event_id: "trial-event-3" },
];
const beliefs: Belief[] = [
  { belief_id: "belief-demo-1", predicate: "onboarding_path_is_learnable", value: true, confidence: 0.84 },
  { belief_id: "belief-demo-2", predicate: "help_is_available", value: true, confidence: 0.91 },
];
const memories: Memory[] = [
  { memory_id: "memory-demo-1", summary: "The guide explained how to inspect available actions.", importance: 0.72, emotional_weight: 0.18 },
];

export function demoTrial(index: number, seed: number): Trial {
  const completed = index % 7 !== 6;
  const help = index % 4 === 0 ? 1 : 0;
  const invalid = index % 5 === 0 ? 1 : 0;
  const persona = demoPersona(seed * 100000 + index);
  const eventIds = ["trial-event-1", "trial-event-2", "trial-event-3"];
  return {
    trial_id: `trial-demo-${seed}-${String(index + 1).padStart(3, "0")}`,
    persona_id: persona.persona_id,
    seed,
    status: completed ? "COMPLETED" : "STOPPED",
    steps: 6 + help + invalid,
    canonical_hash_before: "7f3c9a2b",
    canonical_hash_after: "7f3c9a2b",
    trial_state_hash: `demo-state-${seed}-${index + 1}`,
    traces: [
      {
        trace_id: `trace-demo-${seed}-${index + 1}`,
        persona_id: persona.persona_id,
        persona_version: persona.schema_version,
        policy_version: "onboarding-policy-demo-1.0.0",
        runtime_kind: "UTILITY",
        seed,
        chosen_action: help ? "request_help" : "complete_task",
        candidates: [
          { action: "complete_task", score: help ? 0.61 : 0.82, factors: { goal_alignment: 0.45, comprehension: help ? 0.11 : 0.29, perceived_risk: -0.06 } },
          { action: "request_help", score: help ? 0.73 : 0.43, factors: { uncertainty: help ? 0.38 : 0.12, help_availability: 0.35, social_cost: -0.08 } },
        ],
      },
    ],
    facts: [
      { fact_type: "onboarding.completed", value: completed, unit: null, verifier_version: "onboarding-verifier-demo-1.0.0", evidence_event_ids: completed ? [eventIds[2]] : [] },
      { fact_type: "onboarding.help_requests", value: help, unit: "count", verifier_version: "onboarding-verifier-demo-1.0.0", evidence_event_ids: help ? [eventIds[1]] : [] },
      { fact_type: "kernel.canonical_world_unchanged", value: true, unit: null, verifier_version: "branch-isolation-demo-1.0.0", evidence_event_ids: eventIds },
    ],
    metrics: { invalid_actions: invalid, help_requests: help, comprehended_first_goal: completed || help > 0 },
    events: [
      { event_id: eventIds[0], event_type: "onboarding.presented", actor_name: "Guide", summary: "Presented the available actions.", created_at: "2026-08-17T10:42:01Z", sequence: 1 },
      { event_id: eventIds[1], event_type: help ? "onboarding.help_requested" : "onboarding.action_considered", actor_name: persona.persona_id, summary: help ? "Requested rules help." : "Inspected the first task.", created_at: "2026-08-17T10:42:05Z", sequence: 2 },
      { event_id: eventIds[2], event_type: completed ? "onboarding.completed" : "onboarding.stopped", actor_name: persona.persona_id, summary: completed ? "Completed the opening task." : "Stopped before completion.", created_at: "2026-08-17T10:42:12Z", sequence: 3 },
    ],
    observations,
    beliefs,
    memories,
  };
}

export function demoCohortReport(cohortSize = 100, seeds = [101, 202, 303]): CohortReport {
  const trialCount = cohortSize * seeds.length;
  const completed = Math.round(trialCount * 0.91);
  return {
    scenario_id: "tabletop.player-onboarding",
    scenario_version: "demo-1.0.0",
    trial_count: trialCount,
    completed,
    completion_rate: completed / trialCount,
    canonical_world_unchanged: true,
    metrics: { mean_steps: 7.2, mean_invalid_actions: 0.2, mean_help_requests: 0.25, comprehension_rate: 0.94 },
    sample_trials: seeds.flatMap((seed) => Array.from({ length: 4 }, (_, index) => demoTrial(index, seed))),
  };
}

export const demoJobs: JobSummary[] = [
  {
    job_id: "job-onboarding-demo",
    kind: "SCENARIO",
    status: "COMPLETED",
    progress: 1,
    completed: 300,
    total: 300,
    created_at: "2026-08-17T10:42:00Z",
    report: demoCohortReport(),
  },
];

export const demoCalibrationReport: CalibrationReport = {
  report_id: "calib-demo-2026-08-17",
  synthetic_policy_version: "onboarding-policy-1.0.0",
  evidence_version: "playtest-2026-08-15",
  metrics: [
    { metric: "completion_rate", synthetic_value: 0.91, human_value: 0.87, absolute_error: 0.04, relative_error: 0.046 },
    { metric: "comprehension_rate", synthetic_value: 0.94, human_value: 0.9, absolute_error: 0.04, relative_error: 0.044 },
    { metric: "mean_help_requests", synthetic_value: 0.25, human_value: 0.31, absolute_error: 0.06, relative_error: 0.194 },
  ],
  root_mean_squared_error: 0.0473,
  proposed_policy_version: "onboarding-policy-1.0.0+calibration.demo",
  promotion_status: "REVIEW_REQUIRED",
  human_ground_truth_claimed: false,
};

export const demoTelemetry: TelemetrySettings = {
  human_telemetry_enabled: false,
  local_only: true,
};
