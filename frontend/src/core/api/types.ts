export type DataSource = "live" | "demo";

export type Sourced<T> = {
  data: T;
  source: DataSource;
  reason?: string;
};

export type KernelMeta = {
  contract_version: string;
  kernel: string;
  persona_schema_version: string;
  persona_dimensions: number;
  telemetry_enabled: boolean;
  migrations_from_v1_supported?: boolean;
};

export type WorldSummary = {
  world_id: string;
  name: string;
  status: string;
  current_run_id?: string | null;
  updated_at?: string;
};

export type ActorSummary = {
  actor_id: string;
  world_id?: string;
  display_name: string;
  kind: "HUMAN" | "AGENT" | "SYSTEM";
  roles: string[];
  capabilities: string[];
};

export type EntitySummary = {
  entity_id: string;
  world_id?: string;
  branch_id?: string;
  name: string;
  entity_type: string;
  controller_actor_id?: string | null;
  location?: string;
  health?: number;
  max_health?: number;
  status?: string;
  public_state?: Record<string, unknown>;
};

export type RunSummary = {
  run_id: string;
  world_id: string;
  branch_id?: string;
  name: string;
  kind: "LIVE" | "POPULATION" | "EVALUATION";
  status: string;
  started_at?: string;
  duration?: string;
};

export type SnapshotSummary = {
  snapshot_id: string;
  world_id?: string;
  branch_id?: string;
  name: string;
  state_hash: string;
  event_sequence: number;
  created_at?: string;
};

export type BranchSummary = {
  branch_id: string;
  world_id?: string;
  name: string;
  kind: "CANONICAL" | "TRIAL";
  status: string;
  base_snapshot_id?: string | null;
};

export type EventRecord = {
  event_id: string;
  event_type: string;
  actor_name?: string;
  actor_id?: string;
  summary?: string;
  payload?: Record<string, unknown>;
  created_at: string;
  sequence?: number;
  domain_tags?: string[];
  correlation_id?: string;
  causation_id?: string | null;
};

export type GameState = {
  run: RunSummary | null;
  branch: BranchSummary | null;
  entities: EntitySummary[];
  events: EventRecord[];
  turn: number;
  interaction_status: string;
};

export type PersonaDimension = {
  name: string;
  kind: "enum" | "integer" | "number" | "boolean";
  values?: string[];
  minimum?: number | null;
  maximum?: number | null;
  default?: unknown;
  depends_on?: Record<string, unknown[]>;
  pack?: "core" | "world" | "tabletop" | "accessibility" | string;
};

export type PersonaSchema = {
  version: string;
  dimensions: PersonaDimension[];
};

export type PersonaBlueprint = {
  persona_id: string;
  schema_version: string;
  seed: number;
  generator_version: string;
  source: "synthetic" | "manual" | "imported";
  dimensions: Record<string, unknown>;
  derived_traits: Record<string, string | number | boolean>;
  provenance: Record<string, Record<string, unknown>>;
  validation: { status: "valid" | "invalid"; ruleset_version: string; errors: string[] };
};

export type CompiledPersona = {
  persona_id: string;
  persona_version: string;
  compiler_version: string;
  identity_summary: string;
  policy_weights: Record<string, number>;
  starting_goals: string[];
  retrieval_filters: string[];
};

export type PopulationDefinition = {
  population_id: string;
  world_id?: string;
  branch_id?: string;
  name: string;
  size: number;
  status: string;
  schema_version: string;
  seed: number;
  materialized: number;
  active: number;
  dimensions?: Record<string, Record<string, number>>;
};

export type CohortMember = {
  persona_id: string;
  seed: number;
  dimensions: Record<string, unknown>;
};

export type ScenarioSummary = {
  scenario_id: string;
  version: string;
  name: string;
  description: string;
  cohort_size: number;
  seeds: number[];
  status: string;
  verifier_versions: string[];
  stop_conditions?: string[];
  allowed_actions?: string[];
  metric_contract?: Record<string, unknown>;
};

export type DecisionCandidate = {
  action: string;
  score: number;
  factors: Record<string, number>;
};

export type DecisionTrace = {
  trace_id: string;
  persona_id: string;
  persona_version: string;
  policy_version: string;
  runtime_kind?: string;
  seed: number;
  candidates: DecisionCandidate[];
  chosen_action: string;
  prompt_contract_version?: string | null;
  model_version?: string | null;
};

export type VerifierFact = {
  fact_type: string;
  value: boolean | number | string;
  unit: string | null;
  verifier_version: string;
  evidence_event_ids: string[];
};

export type Observation = {
  observation_id: string;
  summary: string;
  confidence: number;
  source_event_id: string;
};

export type Belief = {
  belief_id: string;
  predicate: string;
  value: unknown;
  confidence: number;
  contradicted_by_event_id?: string | null;
};

export type Memory = {
  memory_id: string;
  summary: string;
  importance: number;
  emotional_weight: number;
};

export type Trial = {
  trial_id: string;
  persona_id: string | null;
  seed: number;
  status: string;
  steps: number;
  canonical_hash_before: string;
  canonical_hash_after: string;
  trial_state_hash: string;
  traces: DecisionTrace[];
  facts: VerifierFact[];
  metrics: Record<string, boolean | number | string>;
  events?: EventRecord[];
  observations?: Observation[];
  beliefs?: Belief[];
  memories?: Memory[];
};

export type CohortReport = {
  scenario_id: string;
  scenario_version: string;
  trial_count: number;
  completed: number;
  completion_rate: number;
  canonical_world_unchanged: boolean;
  metrics: Record<string, number>;
  sample_trials: Trial[];
};

export type JobSummary = {
  job_id: string;
  kind: string;
  status: string;
  progress: number;
  completed: number;
  total: number;
  created_at?: string;
  report?: CohortReport | null;
  error?: string | null;
};

export type CalibrationMetric = {
  metric: string;
  synthetic_value: number;
  human_value: number;
  absolute_error: number;
  relative_error: number | null;
};

export type CalibrationReport = {
  report_id: string;
  synthetic_policy_version: string;
  evidence_version: string;
  metrics: CalibrationMetric[];
  root_mean_squared_error: number;
  proposed_policy_version: string;
  promotion_status: string;
  human_ground_truth_claimed: boolean;
  review_id?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  promotion_id?: string | null;
  promoted_by?: string | null;
  promoted_at?: string | null;
};

export type TelemetrySettings = {
  human_telemetry_enabled: boolean;
  local_only: boolean;
};
