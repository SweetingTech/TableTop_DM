-- TableTop DM v2 clean baseline.
--
-- This is intentionally a fresh-install schema. V1 data and contracts are not
-- migrated. The archived v1 tag remains the compatibility boundary.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tabletop_app') THEN
    CREATE ROLE tabletop_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOBYPASSRLS NOREPLICATION;
  END IF;
END
$$;

ALTER ROLE tabletop_app WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOBYPASSRLS NOREPLICATION;

CREATE SCHEMA IF NOT EXISTS infra_meta;
CREATE SCHEMA IF NOT EXISTS sim;
CREATE SCHEMA IF NOT EXISTS artifacts;
CREATE SCHEMA IF NOT EXISTS persona;
CREATE SCHEMA IF NOT EXISTS cognition;
CREATE SCHEMA IF NOT EXISTS population;
CREATE SCHEMA IF NOT EXISTS experiments;

REVOKE ALL ON SCHEMA infra_meta, sim, artifacts, persona, cognition, population, experiments FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- The migration runner creates this table before applying files. Keeping the
-- declaration here makes the baseline independently inspectable.
CREATE TABLE IF NOT EXISTS infra_meta.schema_migrations (
  version text PRIMARY KEY,
  checksum text NOT NULL
    CONSTRAINT ck_infra_schema_migrations_checksum CHECK (checksum ~ '^[0-9a-f]{64}$'),
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION infra_meta.reject_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME
    USING ERRCODE = '55000';
END
$$;

CREATE TRIGGER infra_schema_migrations_append_only
  BEFORE UPDATE OR DELETE ON infra_meta.schema_migrations
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE TABLE sim.worlds (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 160),
  status text NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'ENDED', 'ARCHIVED')),
  domain_packs text[] NOT NULL DEFAULT '{}'::text[],
  settings jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(settings) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sim.branches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL REFERENCES sim.worlds(id) ON DELETE RESTRICT,
  branch_kind text NOT NULL CHECK (branch_kind IN ('CANONICAL', 'TRIAL')),
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 160),
  base_snapshot_id uuid,
  seed bigint,
  status text NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'COMPLETED', 'FAILED', 'ARCHIVED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  UNIQUE (world_id, id),
  UNIQUE (world_id, name),
  CHECK ((status IN ('COMPLETED', 'FAILED', 'ARCHIVED')) OR completed_at IS NULL),
  CHECK (branch_kind = 'TRIAL' OR base_snapshot_id IS NULL)
);
CREATE UNIQUE INDEX uq_sim_one_canonical_branch
  ON sim.branches(world_id) WHERE branch_kind = 'CANONICAL';
CREATE INDEX idx_sim_branches_world_status
  ON sim.branches(world_id, branch_kind, status);

CREATE TABLE sim.branch_projections (
  branch_id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
  state jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(state) = 'object'),
  state_hash text NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE CASCADE
);

CREATE TABLE artifacts.objects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid REFERENCES sim.worlds(id) ON DELETE RESTRICT,
  branch_id uuid,
  artifact_kind text NOT NULL,
  uri text NOT NULL CHECK (length(btrim(uri)) > 0),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  media_type text NOT NULL DEFAULT 'application/octet-stream',
  byte_size bigint CHECK (byte_size IS NULL OR byte_size >= 0),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, id),
  UNIQUE NULLS NOT DISTINCT (world_id, artifact_kind, content_hash),
  CHECK (branch_id IS NULL OR world_id IS NOT NULL),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT
);
CREATE INDEX idx_artifacts_objects_world_kind
  ON artifacts.objects(world_id, artifact_kind, created_at DESC);

CREATE TABLE sim.snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  source_branch_id uuid NOT NULL,
  through_event_seq bigint NOT NULL DEFAULT 0 CHECK (through_event_seq >= 0),
  projection_version bigint NOT NULL CHECK (projection_version >= 0),
  state_hash text NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
  artifact_id uuid NOT NULL,
  contract_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, id),
  UNIQUE (world_id, source_branch_id, through_event_seq, state_hash),
  FOREIGN KEY (world_id, source_branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, artifact_id)
    REFERENCES artifacts.objects(world_id, id) ON DELETE RESTRICT
);

ALTER TABLE sim.branches
  ADD CONSTRAINT fk_sim_branch_base_snapshot
  FOREIGN KEY (world_id, base_snapshot_id)
  REFERENCES sim.snapshots(world_id, id) ON DELETE RESTRICT;

CREATE TABLE sim.runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_kind text NOT NULL CHECK (run_kind IN ('LIVE', 'POPULATION', 'EVALUATION')),
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'RUNNING', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED')),
  policy_version text,
  model_assignment jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(model_assignment) = 'object'),
  seed bigint,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, branch_id, id),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT,
  CHECK (completed_at IS NULL OR started_at IS NOT NULL),
  CHECK (completed_at IS NULL OR completed_at >= started_at)
);
CREATE INDEX idx_sim_runs_branch_status ON sim.runs(world_id, branch_id, status);
CREATE INDEX idx_sim_runs_world_kind_created ON sim.runs(world_id, run_kind, created_at DESC);

CREATE TABLE sim.interactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  interaction_type text NOT NULL,
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'ACTIVE', 'COMPLETED', 'ABORTED')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  UNIQUE (world_id, branch_id, run_id, id),
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX idx_sim_interactions_run_status
  ON sim.interactions(world_id, branch_id, run_id, status);

CREATE TABLE sim.actors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_kind text NOT NULL CHECK (actor_kind IN ('HUMAN', 'AGENT', 'SYSTEM')),
  display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 160),
  auth_subject text UNIQUE,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sim.actor_roles (
  world_id uuid NOT NULL REFERENCES sim.worlds(id) ON DELETE CASCADE,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE CASCADE,
  role text NOT NULL,
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, actor_id, role)
);

CREATE TABLE sim.actor_capabilities (
  world_id uuid NOT NULL REFERENCES sim.worlds(id) ON DELETE CASCADE,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE CASCADE,
  capability text NOT NULL CHECK (capability ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, actor_id, capability)
);
CREATE INDEX idx_sim_actor_capability_lookup
  ON sim.actor_capabilities(actor_id, world_id, capability);

CREATE TABLE sim.entities (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_type text NOT NULL,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
  public_state jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(public_state) = 'object'),
  secret_state jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(secret_state) = 'object'),
  controller_actor_id uuid REFERENCES sim.actors(id) ON DELETE SET NULL,
  control_version bigint NOT NULL DEFAULT 0 CHECK (control_version >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (branch_id, id),
  UNIQUE (world_id, branch_id, id),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_sim_entities_world_branch_type
  ON sim.entities(world_id, branch_id, entity_type);
CREATE INDEX idx_sim_entities_controller
  ON sim.entities(world_id, branch_id, controller_actor_id)
  WHERE controller_actor_id IS NOT NULL;
CREATE INDEX idx_sim_entities_public_state ON sim.entities USING gin(public_state);

CREATE TABLE sim.schedules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_id uuid,
  schedule_type text NOT NULL,
  due_at timestamptz NOT NULL,
  recurrence jsonb,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
  status text NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'CANCELLED', 'FAILED')),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_sim_schedules_due
  ON sim.schedules(status, due_at) WHERE status = 'PENDING';

CREATE TABLE sim.command_log (
  seq_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  command_id uuid NOT NULL UNIQUE,
  command_type text NOT NULL,
  command_version text NOT NULL,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  interaction_id uuid,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  embodied_entity_id uuid,
  parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters) = 'object'),
  result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
  resulting_state_hash text NOT NULL CHECK (resulting_state_hash ~ '^[0-9a-f]{64}$'),
  seed bigint,
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  correlation_id uuid NOT NULL,
  causation_id uuid,
  committed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, actor_id, idempotency_key),
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, run_id, interaction_id)
    REFERENCES sim.interactions(world_id, branch_id, run_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, embodied_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE RESTRICT
);
CREATE INDEX idx_sim_command_log_run_seq
  ON sim.command_log(world_id, branch_id, run_id, seq_id);
CREATE INDEX idx_sim_command_log_correlation ON sim.command_log(correlation_id, seq_id);

CREATE TABLE sim.events (
  seq_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id uuid NOT NULL UNIQUE,
  event_version integer NOT NULL CHECK (event_version >= 2),
  contract_version text NOT NULL,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  interaction_id uuid,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  embodied_entity_id uuid,
  event_type text NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  observed_by uuid[] NOT NULL DEFAULT '{}'::uuid[],
  visible_to uuid[] NOT NULL,
  parent_event_id uuid REFERENCES sim.events(event_id) DEFERRABLE INITIALLY DEFERRED,
  correlation_id uuid NOT NULL,
  causation_id uuid REFERENCES sim.events(event_id) DEFERRABLE INITIALLY DEFERRED,
  domain_tags text[] NOT NULL DEFAULT '{}'::text[],
  idempotency_key text,
  persona_version text,
  policy_version text,
  prompt_contract_version text,
  model_version text,
  seed bigint,
  decision_trace_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (cardinality(visible_to) > 0),
  UNIQUE (run_id, actor_id, idempotency_key),
  UNIQUE (world_id, branch_id, event_id),
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, run_id, interaction_id)
    REFERENCES sim.interactions(world_id, branch_id, run_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, embodied_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE RESTRICT
);
CREATE INDEX idx_sim_events_run_seq
  ON sim.events(world_id, branch_id, run_id, seq_id);
CREATE INDEX idx_sim_events_branch_seq ON sim.events(world_id, branch_id, seq_id);
CREATE INDEX idx_sim_events_correlation ON sim.events(correlation_id, seq_id);
CREATE INDEX idx_sim_events_visible_to ON sim.events USING gin(visible_to);
CREATE INDEX idx_sim_events_observed_by ON sim.events USING gin(observed_by);
CREATE INDEX idx_sim_events_domain_tags ON sim.events USING gin(domain_tags);

CREATE TABLE sim.outbox (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id uuid NOT NULL UNIQUE REFERENCES sim.events(event_id) ON DELETE RESTRICT,
  topic text NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  claimed_at timestamptz,
  claimed_by text,
  published_at timestamptz,
  last_error text,
  CHECK (published_at IS NULL OR published_at >= available_at)
);
CREATE INDEX idx_sim_outbox_pending
  ON sim.outbox(available_at, id) WHERE published_at IS NULL;

CREATE TRIGGER sim_command_log_append_only
  BEFORE UPDATE OR DELETE ON sim.command_log
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
CREATE TRIGGER sim_events_append_only
  BEFORE UPDATE OR DELETE ON sim.events
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE TABLE persona.schema_versions (
  version text PRIMARY KEY,
  schema_hash text NOT NULL CHECK (schema_hash ~ '^[0-9a-f]{64}$'),
  definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
  status text NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'RETIRED')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE persona.blueprints (
  persona_id uuid NOT NULL,
  version_id uuid NOT NULL DEFAULT gen_random_uuid(),
  parent_version_id uuid,
  schema_version text NOT NULL REFERENCES persona.schema_versions(version) ON DELETE RESTRICT,
  seed bigint NOT NULL,
  generator_version text NOT NULL,
  source text NOT NULL CHECK (source IN ('synthetic', 'manual', 'imported')),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  dimensions jsonb NOT NULL CHECK (jsonb_typeof(dimensions) = 'object'),
  derived_traits jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(derived_traits) = 'object'),
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provenance) = 'object'),
  validation jsonb NOT NULL CHECK (jsonb_typeof(validation) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (persona_id, version_id),
  UNIQUE (version_id),
  UNIQUE (persona_id, content_hash),
  FOREIGN KEY (persona_id, parent_version_id)
    REFERENCES persona.blueprints(persona_id, version_id) ON DELETE RESTRICT,
  CHECK (parent_version_id IS NULL OR parent_version_id <> version_id)
);
CREATE INDEX idx_persona_blueprints_dimensions ON persona.blueprints USING gin(dimensions);
CREATE INDEX idx_persona_blueprints_schema_seed ON persona.blueprints(schema_version, seed);
CREATE INDEX idx_persona_blueprints_lineage ON persona.blueprints(persona_id, parent_version_id);

CREATE TABLE persona.compiled_profiles (
  persona_id uuid NOT NULL,
  persona_version_id uuid NOT NULL,
  compiler_version text NOT NULL,
  identity_summary text NOT NULL,
  policy_weights jsonb NOT NULL CHECK (jsonb_typeof(policy_weights) = 'object'),
  starting_goals jsonb NOT NULL CHECK (jsonb_typeof(starting_goals) = 'array'),
  starting_beliefs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(starting_beliefs) = 'array'),
  starting_relationships jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(starting_relationships) = 'array'),
  routine_templates jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(routine_templates) = 'array'),
  capability_modifiers jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(capability_modifiers) = 'object'),
  retrieval_filters jsonb NOT NULL CHECK (jsonb_typeof(retrieval_filters) = 'object'),
  compiled_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (persona_id, persona_version_id, compiler_version),
  FOREIGN KEY (persona_id, persona_version_id)
    REFERENCES persona.blueprints(persona_id, version_id) ON DELETE CASCADE
);

CREATE TABLE persona.entity_assignments (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  persona_id uuid NOT NULL,
  persona_version_id uuid NOT NULL,
  assigned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, branch_id, entity_id),
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (persona_id, persona_version_id)
    REFERENCES persona.blueprints(persona_id, version_id) ON DELETE RESTRICT
);

CREATE TRIGGER persona_blueprints_append_only
  BEFORE UPDATE OR DELETE ON persona.blueprints
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
CREATE TRIGGER persona_compiled_profiles_append_only
  BEFORE UPDATE OR DELETE ON persona.compiled_profiles
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE TABLE cognition.mind_states (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  mood text NOT NULL DEFAULT 'NEUTRAL',
  stress numeric(6,3) NOT NULL DEFAULT 0 CHECK (stress BETWEEN 0 AND 100),
  attention_budget numeric(6,3) NOT NULL DEFAULT 100 CHECK (attention_budget BETWEEN 0 AND 100),
  active_plan jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(active_plan) = 'array'),
  goals jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(goals) = 'array'),
  needs jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(needs) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, branch_id, entity_id),
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);

CREATE TABLE cognition.observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  observer_entity_id uuid NOT NULL,
  source_event_id uuid NOT NULL REFERENCES sim.events(event_id) ON DELETE RESTRICT,
  perceived_payload jsonb NOT NULL CHECK (jsonb_typeof(perceived_payload) = 'object'),
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  observed_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (world_id, branch_id, observer_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_cognition_observations_observer_time
  ON cognition.observations(world_id, branch_id, observer_entity_id, observed_at DESC);

CREATE TABLE cognition.beliefs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  subject_type text NOT NULL,
  subject_id uuid,
  predicate text NOT NULL,
  value jsonb NOT NULL,
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  source_observation_id uuid REFERENCES cognition.observations(id) ON DELETE SET NULL,
  contradicted_by_event_id uuid REFERENCES sim.events(event_id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_cognition_beliefs_subject
  ON cognition.beliefs(world_id, branch_id, entity_id, subject_type, subject_id, predicate);
CREATE INDEX idx_cognition_beliefs_active
  ON cognition.beliefs(world_id, branch_id, entity_id, updated_at DESC)
  WHERE contradicted_by_event_id IS NULL;

CREATE TABLE cognition.memories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  source_event_id uuid NOT NULL REFERENCES sim.events(event_id) ON DELETE RESTRICT,
  summary text NOT NULL,
  emotional_weight numeric(5,4) NOT NULL CHECK (emotional_weight BETWEEN -1 AND 1),
  importance numeric(5,4) NOT NULL CHECK (importance BETWEEN 0 AND 1),
  recall_strength numeric(5,4) NOT NULL CHECK (recall_strength BETWEEN 0 AND 1),
  visibility text NOT NULL DEFAULT 'PRIVATE'
    CHECK (visibility IN ('PRIVATE', 'CONTROLLER', 'WORLD')),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);
CREATE INDEX idx_cognition_memories_recall
  ON cognition.memories(world_id, branch_id, entity_id, importance DESC, recall_strength DESC);

CREATE TABLE cognition.relationships (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  source_entity_id uuid NOT NULL,
  target_entity_id uuid NOT NULL,
  trust numeric(7,3) NOT NULL DEFAULT 0 CHECK (trust BETWEEN -100 AND 100),
  affection numeric(7,3) NOT NULL DEFAULT 0 CHECK (affection BETWEEN -100 AND 100),
  respect numeric(7,3) NOT NULL DEFAULT 0 CHECK (respect BETWEEN -100 AND 100),
  fear numeric(7,3) NOT NULL DEFAULT 0 CHECK (fear BETWEEN 0 AND 100),
  resentment numeric(7,3) NOT NULL DEFAULT 0 CHECK (resentment BETWEEN 0 AND 100),
  obligation numeric(7,3) NOT NULL DEFAULT 0 CHECK (obligation BETWEEN -100 AND 100),
  familiarity numeric(7,3) NOT NULL DEFAULT 0 CHECK (familiarity BETWEEN 0 AND 100),
  suspicion numeric(7,3) NOT NULL DEFAULT 0 CHECK (suspicion BETWEEN 0 AND 100),
  ideological_alignment numeric(7,3) NOT NULL DEFAULT 0 CHECK (ideological_alignment BETWEEN -100 AND 100),
  dependency numeric(7,3) NOT NULL DEFAULT 0 CHECK (dependency BETWEEN 0 AND 100),
  attraction numeric(7,3) CHECK (attraction BETWEEN -100 AND 100),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, branch_id, source_entity_id, target_entity_id),
  CHECK (source_entity_id <> target_entity_id),
  FOREIGN KEY (world_id, branch_id, source_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, target_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);

CREATE TABLE cognition.relationship_changes (
  id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  source_entity_id uuid NOT NULL,
  target_entity_id uuid NOT NULL,
  source_event_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  event_type text NOT NULL CHECK (length(btrim(event_type)) BETWEEN 1 AND 120),
  policy_version text NOT NULL,
  requested_deltas jsonb NOT NULL CHECK (jsonb_typeof(requested_deltas) = 'object'),
  applied_deltas jsonb NOT NULL CHECK (jsonb_typeof(applied_deltas) = 'object'),
  before_vector jsonb NOT NULL CHECK (jsonb_typeof(before_vector) = 'object'),
  after_vector jsonb NOT NULL CHECK (jsonb_typeof(after_vector) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, branch_id, source_entity_id, target_entity_id, source_event_id),
  CHECK (source_entity_id <> target_entity_id),
  FOREIGN KEY (world_id, branch_id, source_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, target_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, source_event_id)
    REFERENCES sim.events(world_id, branch_id, event_id) ON DELETE RESTRICT
);
CREATE INDEX idx_cognition_relationship_changes_source
  ON cognition.relationship_changes(
    world_id, branch_id, source_entity_id, created_at, id
  );
CREATE INDEX idx_cognition_relationship_changes_event
  ON cognition.relationship_changes(source_event_id);

CREATE TABLE cognition.runtime_assignments (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  runtime_kind text NOT NULL
    CHECK (runtime_kind IN ('DETERMINISTIC', 'UTILITY', 'PLANNER', 'LOCAL_LLM', 'HOSTED_LLM', 'HUMAN', 'REPLAY')),
  runtime_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(runtime_config) = 'object'),
  assigned_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, branch_id, run_id, entity_id),
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE
);

CREATE TABLE cognition.decision_traces (
  id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  persona_id uuid,
  persona_version_id uuid,
  policy_version text NOT NULL,
  runtime_kind text NOT NULL,
  model_version text,
  prompt_contract_version text,
  seed bigint NOT NULL,
  candidates jsonb NOT NULL CHECK (jsonb_typeof(candidates) = 'array'),
  chosen_action text NOT NULL,
  explanation jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(explanation) = 'object'),
  artifact_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, artifact_id)
    REFERENCES artifacts.objects(world_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (persona_id, persona_version_id)
    REFERENCES persona.blueprints(persona_id, version_id) ON DELETE RESTRICT,
  CHECK ((persona_id IS NULL) = (persona_version_id IS NULL))
);
CREATE INDEX idx_cognition_decision_traces_run
  ON cognition.decision_traces(world_id, branch_id, run_id, created_at, id);

ALTER TABLE sim.events
  ADD CONSTRAINT fk_sim_event_decision_trace
  FOREIGN KEY (decision_trace_id) REFERENCES cognition.decision_traces(id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TRIGGER cognition_observations_append_only
  BEFORE UPDATE OR DELETE ON cognition.observations
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
CREATE TRIGGER cognition_memories_append_only
  BEFORE UPDATE OR DELETE ON cognition.memories
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
CREATE TRIGGER cognition_relationship_changes_append_only
  BEFORE UPDATE OR DELETE ON cognition.relationship_changes
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
CREATE TRIGGER cognition_decision_traces_append_only
  BEFORE UPDATE OR DELETE ON cognition.decision_traces
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE TABLE population.definitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  population_key text NOT NULL,
  version text NOT NULL,
  schema_version text NOT NULL REFERENCES persona.schema_versions(version) ON DELETE RESTRICT,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  distributions jsonb NOT NULL CHECK (jsonb_typeof(distributions) = 'object'),
  target_size bigint NOT NULL CHECK (target_size > 0),
  seed bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (population_key, version),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT
);

CREATE TABLE population.pools (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  definition_id uuid NOT NULL REFERENCES population.definitions(id) ON DELETE RESTRICT,
  artifact_id uuid NOT NULL REFERENCES artifacts.objects(id) ON DELETE RESTRICT,
  row_count bigint NOT NULL CHECK (row_count >= 0),
  generator_version text NOT NULL,
  state text NOT NULL CHECK (state IN ('GENERATING', 'READY', 'FAILED', 'ARCHIVED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);

CREATE TABLE population.cohorts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pool_id uuid NOT NULL REFERENCES population.pools(id) ON DELETE RESTRICT,
  name text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(filters) = 'object'),
  sampling jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(sampling) = 'object'),
  weight_column text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pool_id, name)
);

CREATE TABLE population.materialized_people (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  population_id uuid NOT NULL REFERENCES population.definitions(id) ON DELETE RESTRICT,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  persona_id uuid NOT NULL,
  persona_version_id uuid NOT NULL,
  entity_id uuid,
  household_id uuid,
  occupation text,
  finances jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(finances) = 'object'),
  persistent_state jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(persistent_state) = 'object'),
  active_state jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(active_state) = 'object'),
  compressed_state jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(compressed_state) = 'object'),
  activation_state text NOT NULL DEFAULT 'MATERIALIZED'
    CHECK (activation_state IN ('MATERIALIZED', 'ACTIVE', 'COMPRESSED', 'ARCHIVED')),
  lifecycle_version bigint NOT NULL DEFAULT 0 CHECK (lifecycle_version >= 0),
  world_step bigint NOT NULL DEFAULT 0 CHECK (world_step >= 0),
  next_update_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, branch_id, persona_id),
  UNIQUE (population_id, persona_id),
  FOREIGN KEY (world_id, branch_id)
    REFERENCES sim.branches(world_id, id) ON DELETE CASCADE,
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE SET NULL (entity_id),
  FOREIGN KEY (persona_id, persona_version_id)
    REFERENCES persona.blueprints(persona_id, version_id) ON DELETE RESTRICT
);
CREATE INDEX idx_population_materialized_activation
  ON population.materialized_people(world_id, branch_id, activation_state, next_update_at);

CREATE TABLE population.lifecycle_transitions (
  transition_id uuid PRIMARY KEY,
  population_id uuid NOT NULL REFERENCES population.definitions(id) ON DELETE RESTRICT,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  persona_id uuid NOT NULL,
  sequence bigint NOT NULL CHECK (sequence > 0),
  lifecycle_version bigint NOT NULL CHECK (lifecycle_version > 0),
  from_level text NOT NULL CHECK (from_level IN ('STATISTICAL', 'MATERIALIZED', 'ACTIVE')),
  to_level text NOT NULL CHECK (to_level IN ('STATISTICAL', 'MATERIALIZED', 'ACTIVE')),
  reason text NOT NULL CHECK (length(btrim(reason)) > 0),
  world_step bigint NOT NULL CHECK (world_step >= 0),
  persistent_state_hash text NOT NULL CHECK (persistent_state_hash ~ '^[0-9a-f]{64}$'),
  active_state_hash text NOT NULL CHECK (active_state_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (population_id, persona_id, lifecycle_version),
  FOREIGN KEY (population_id, persona_id)
    REFERENCES population.materialized_people(population_id, persona_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, persona_id)
    REFERENCES population.materialized_people(world_id, branch_id, persona_id)
    ON DELETE RESTRICT
);

CREATE TRIGGER population_lifecycle_transitions_append_only
  BEFORE UPDATE OR DELETE ON population.lifecycle_transitions
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE TABLE experiments.scenarios (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_key text NOT NULL,
  version text NOT NULL,
  definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
  metric_contract jsonb NOT NULL CHECK (jsonb_typeof(metric_contract) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scenario_key, version)
);

CREATE TABLE experiments.trials (
  id uuid PRIMARY KEY,
  scenario_id uuid NOT NULL REFERENCES experiments.scenarios(id) ON DELETE RESTRICT,
  cohort_id uuid REFERENCES population.cohorts(id) ON DELETE RESTRICT,
  persona_id uuid,
  persona_version_id uuid,
  world_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  seed bigint NOT NULL,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
  attempt integer NOT NULL DEFAULT 1 CHECK (attempt > 0),
  failure_code text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (branch_id),
  UNIQUE (run_id),
  UNIQUE NULLS NOT DISTINCT (scenario_id, persona_id, seed, attempt),
  FOREIGN KEY (world_id, snapshot_id)
    REFERENCES sim.snapshots(world_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (persona_id, persona_version_id)
    REFERENCES persona.blueprints(persona_id, version_id) ON DELETE RESTRICT,
  CHECK ((persona_id IS NULL) = (persona_version_id IS NULL)),
  CHECK (completed_at IS NULL OR started_at IS NOT NULL)
);
CREATE INDEX idx_experiments_trials_scenario_status
  ON experiments.trials(scenario_id, status, created_at);

CREATE TABLE experiments.verifier_facts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  trial_id uuid NOT NULL REFERENCES experiments.trials(id) ON DELETE RESTRICT,
  fact_type text NOT NULL,
  value jsonb NOT NULL,
  unit text,
  evidence_event_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
  verifier_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_experiments_facts_trial_type
  ON experiments.verifier_facts(trial_id, fact_type);

CREATE TABLE experiments.metrics (
  trial_id uuid NOT NULL REFERENCES experiments.trials(id) ON DELETE RESTRICT,
  metric_name text NOT NULL,
  metric_value double precision NOT NULL,
  metric_version text NOT NULL,
  dimensions jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(dimensions) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (trial_id, metric_name, metric_version, dimensions)
);
CREATE INDEX idx_experiments_metrics_name_value
  ON experiments.metrics(metric_name, metric_value);

CREATE TABLE experiments.jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_kind text NOT NULL,
  queue_name text NOT NULL DEFAULT 'experiments',
  rq_job_id text UNIQUE,
  status text NOT NULL DEFAULT 'QUEUED'
    CHECK (status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
  parameters jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(parameters) = 'object'),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
  result_artifact_id uuid REFERENCES artifacts.objects(id) ON DELETE RESTRICT,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  completed_at timestamptz
);
CREATE INDEX idx_experiments_jobs_queue_status
  ON experiments.jobs(queue_name, status, created_at);

CREATE TABLE experiments.comparisons (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  baseline_run_id uuid NOT NULL REFERENCES sim.runs(id) ON DELETE RESTRICT,
  candidate_run_id uuid NOT NULL REFERENCES sim.runs(id) ON DELETE RESTRICT,
  metric_contract_version text NOT NULL,
  result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (baseline_run_id <> candidate_run_id)
);

CREATE TABLE experiments.calibration_reports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  policy_version text NOT NULL,
  evidence_version text NOT NULL,
  synthetic_metrics jsonb NOT NULL CHECK (jsonb_typeof(synthetic_metrics) = 'object'),
  human_metrics jsonb NOT NULL CHECK (jsonb_typeof(human_metrics) = 'object'),
  result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
  promotion_status text NOT NULL DEFAULT 'REVIEW_REQUIRED'
    CHECK (promotion_status IN ('REVIEW_REQUIRED', 'APPROVED', 'REJECTED')),
  human_ground_truth_claimed boolean NOT NULL DEFAULT false CHECK (NOT human_ground_truth_claimed),
  reviewed_by_actor_id uuid REFERENCES sim.actors(id) ON DELETE SET NULL,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE experiments.telemetry_settings (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  human_telemetry_enabled boolean NOT NULL DEFAULT false,
  local_only boolean NOT NULL DEFAULT true CHECK (local_only),
  retention_days integer NOT NULL DEFAULT 30 CHECK (retention_days BETWEEN 1 AND 3650),
  enabled_at timestamptz,
  enabled_by_actor_id uuid REFERENCES sim.actors(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO experiments.telemetry_settings(singleton, human_telemetry_enabled, local_only)
VALUES (true, false, true);

CREATE TABLE experiments.telemetry_captures (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL REFERENCES sim.worlds(id) ON DELETE RESTRICT,
  actor_id uuid REFERENCES sim.actors(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  consent_version text NOT NULL,
  captured_at timestamptz NOT NULL DEFAULT now()
);

-- PostgreSQL does not create child-side indexes for foreign keys. These cover
-- referential checks, cascade/set-null work, common branch joins, and the actor
-- lookups used by RLS without forcing sequential scans as ledgers grow.
CREATE INDEX idx_sim_branches_base_snapshot
  ON sim.branches(world_id, base_snapshot_id) WHERE base_snapshot_id IS NOT NULL;
CREATE INDEX idx_artifacts_objects_branch
  ON artifacts.objects(world_id, branch_id) WHERE branch_id IS NOT NULL;
CREATE INDEX idx_sim_snapshots_artifact
  ON sim.snapshots(world_id, artifact_id);
CREATE INDEX idx_sim_actor_roles_actor
  ON sim.actor_roles(actor_id, world_id);
CREATE INDEX idx_sim_entities_controller_actor
  ON sim.entities(controller_actor_id) WHERE controller_actor_id IS NOT NULL;
CREATE INDEX idx_sim_schedules_entity
  ON sim.schedules(world_id, branch_id, entity_id) WHERE entity_id IS NOT NULL;
CREATE INDEX idx_sim_command_log_actor
  ON sim.command_log(actor_id, committed_at);
CREATE INDEX idx_sim_command_log_interaction
  ON sim.command_log(world_id, branch_id, run_id, interaction_id)
  WHERE interaction_id IS NOT NULL;
CREATE INDEX idx_sim_command_log_entity
  ON sim.command_log(world_id, branch_id, embodied_entity_id)
  WHERE embodied_entity_id IS NOT NULL;
CREATE INDEX idx_sim_events_actor
  ON sim.events(actor_id, seq_id);
CREATE INDEX idx_sim_events_parent
  ON sim.events(parent_event_id) WHERE parent_event_id IS NOT NULL;
CREATE INDEX idx_sim_events_causation
  ON sim.events(causation_id) WHERE causation_id IS NOT NULL;
CREATE INDEX idx_sim_events_interaction
  ON sim.events(world_id, branch_id, run_id, interaction_id)
  WHERE interaction_id IS NOT NULL;
CREATE INDEX idx_sim_events_entity
  ON sim.events(world_id, branch_id, embodied_entity_id)
  WHERE embodied_entity_id IS NOT NULL;
CREATE INDEX idx_sim_events_decision_trace
  ON sim.events(decision_trace_id) WHERE decision_trace_id IS NOT NULL;
CREATE INDEX idx_persona_entity_assignments_persona
  ON persona.entity_assignments(persona_id, persona_version_id);
CREATE INDEX idx_cognition_observations_event
  ON cognition.observations(source_event_id);
CREATE INDEX idx_cognition_beliefs_observation
  ON cognition.beliefs(source_observation_id) WHERE source_observation_id IS NOT NULL;
CREATE INDEX idx_cognition_beliefs_contradiction
  ON cognition.beliefs(contradicted_by_event_id) WHERE contradicted_by_event_id IS NOT NULL;
CREATE INDEX idx_cognition_memories_event
  ON cognition.memories(source_event_id);
CREATE INDEX idx_cognition_relationships_target
  ON cognition.relationships(world_id, branch_id, target_entity_id);
CREATE INDEX idx_cognition_runtime_entity
  ON cognition.runtime_assignments(world_id, branch_id, entity_id);
CREATE INDEX idx_cognition_decision_entity
  ON cognition.decision_traces(world_id, branch_id, entity_id);
CREATE INDEX idx_cognition_decision_persona
  ON cognition.decision_traces(persona_id, persona_version_id)
  WHERE persona_id IS NOT NULL;
CREATE INDEX idx_cognition_decision_artifact
  ON cognition.decision_traces(world_id, artifact_id) WHERE artifact_id IS NOT NULL;
CREATE INDEX idx_population_definitions_schema
  ON population.definitions(schema_version);
CREATE INDEX idx_population_definitions_branch
  ON population.definitions(world_id, branch_id);
CREATE INDEX idx_population_pools_definition
  ON population.pools(definition_id);
CREATE INDEX idx_population_pools_artifact
  ON population.pools(artifact_id);
CREATE INDEX idx_population_materialized_persona
  ON population.materialized_people(persona_id, persona_version_id);
CREATE INDEX idx_population_materialized_population
  ON population.materialized_people(population_id, activation_state);
CREATE INDEX idx_population_materialized_entity
  ON population.materialized_people(world_id, branch_id, entity_id)
  WHERE entity_id IS NOT NULL;
CREATE INDEX idx_population_lifecycle_branch_step
  ON population.lifecycle_transitions(world_id, branch_id, world_step, transition_id);
CREATE INDEX idx_experiments_trials_cohort
  ON experiments.trials(cohort_id) WHERE cohort_id IS NOT NULL;
CREATE INDEX idx_experiments_trials_persona
  ON experiments.trials(persona_id, persona_version_id) WHERE persona_id IS NOT NULL;
CREATE INDEX idx_experiments_trials_snapshot
  ON experiments.trials(world_id, snapshot_id);
CREATE INDEX idx_experiments_jobs_artifact
  ON experiments.jobs(result_artifact_id) WHERE result_artifact_id IS NOT NULL;
CREATE INDEX idx_experiments_comparisons_baseline
  ON experiments.comparisons(baseline_run_id);
CREATE INDEX idx_experiments_comparisons_candidate
  ON experiments.comparisons(candidate_run_id);
CREATE INDEX idx_experiments_calibration_reviewer
  ON experiments.calibration_reports(reviewed_by_actor_id)
  WHERE reviewed_by_actor_id IS NOT NULL;
CREATE INDEX idx_experiments_telemetry_actor
  ON experiments.telemetry_captures(actor_id) WHERE actor_id IS NOT NULL;
CREATE INDEX idx_experiments_telemetry_world_time
  ON experiments.telemetry_captures(world_id, captured_at DESC);

CREATE TRIGGER experiments_verifier_facts_append_only
  BEFORE UPDATE OR DELETE ON experiments.verifier_facts
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
CREATE TRIGGER experiments_metrics_append_only
  BEFORE UPDATE OR DELETE ON experiments.metrics
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
-- Captures are immutable, but explicit consent deletion and retention expiry must
-- remain possible.  This is intentionally weaker than the canonical ledger's
-- append-only contract.
CREATE TRIGGER experiments_telemetry_captures_immutable
  BEFORE UPDATE ON experiments.telemetry_captures
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

-- Fail-closed actor context. Invalid and missing values both resolve to NULL.
CREATE OR REPLACE FUNCTION sim.current_actor_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  raw_actor text;
BEGIN
  raw_actor := current_setting('app.actor_id', true);
  IF raw_actor IS NULL OR btrim(raw_actor) = '' THEN
    RETURN NULL;
  END IF;
  BEGIN
    RETURN raw_actor::uuid;
  EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
  END;
END
$$;

CREATE OR REPLACE FUNCTION sim.has_world_capability(target_world_id uuid, required_capability text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sim
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM sim.actor_capabilities capability
    JOIN sim.actors actor ON actor.id = capability.actor_id AND actor.is_active
    WHERE capability.world_id = target_world_id
      AND capability.actor_id = (SELECT sim.current_actor_id())
      AND capability.capability = required_capability
  )
$$;

CREATE OR REPLACE FUNCTION sim.can_mutate_branch(target_world_id uuid, target_branch_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sim
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM sim.branches branch
    WHERE branch.world_id = target_world_id
      AND branch.id = target_branch_id
      AND branch.status = 'ACTIVE'
      AND (
        (branch.branch_kind = 'CANONICAL' AND sim.has_world_capability(target_world_id, 'action.commit'))
        OR
        (branch.branch_kind = 'TRIAL' AND sim.has_world_capability(target_world_id, 'action.propose'))
      )
  )
$$;

REVOKE ALL ON FUNCTION sim.current_actor_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION sim.has_world_capability(uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION sim.can_mutate_branch(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.current_actor_id() TO tabletop_app;
GRANT EXECUTE ON FUNCTION sim.has_world_capability(uuid, text) TO tabletop_app;
GRANT EXECUTE ON FUNCTION sim.can_mutate_branch(uuid, uuid) TO tabletop_app;

ALTER TABLE sim.branch_projections ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.branch_projections FORCE ROW LEVEL SECURITY;
CREATE POLICY branch_projections_read ON sim.branch_projections FOR SELECT
  USING (sim.has_world_capability(world_id, 'world.read') OR sim.can_mutate_branch(world_id, branch_id));
CREATE POLICY branch_projections_write ON sim.branch_projections FOR ALL
  USING (sim.can_mutate_branch(world_id, branch_id))
  WITH CHECK (sim.can_mutate_branch(world_id, branch_id));

ALTER TABLE sim.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.entities FORCE ROW LEVEL SECURITY;
CREATE POLICY entities_read ON sim.entities FOR SELECT
  USING (
    controller_actor_id = (SELECT sim.current_actor_id())
    OR sim.has_world_capability(world_id, 'entity.read.secret')
  );
CREATE POLICY entities_write ON sim.entities FOR ALL
  USING (
    controller_actor_id = (SELECT sim.current_actor_id())
    OR sim.has_world_capability(world_id, 'entity.control')
  )
  WITH CHECK (
    controller_actor_id = (SELECT sim.current_actor_id())
    OR sim.has_world_capability(world_id, 'entity.control')
  );

ALTER TABLE sim.command_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.command_log FORCE ROW LEVEL SECURITY;
CREATE POLICY command_log_read ON sim.command_log FOR SELECT
  USING (actor_id = (SELECT sim.current_actor_id()) OR sim.has_world_capability(world_id, 'world.read.all'));
CREATE POLICY command_log_insert ON sim.command_log FOR INSERT
  WITH CHECK (actor_id = (SELECT sim.current_actor_id()) AND sim.can_mutate_branch(world_id, branch_id));

ALTER TABLE sim.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.events FORCE ROW LEVEL SECURITY;
CREATE POLICY events_read ON sim.events FOR SELECT
  USING (
    (SELECT sim.current_actor_id()) = ANY(visible_to)
    OR sim.has_world_capability(world_id, 'world.read.all')
  );
CREATE POLICY events_insert ON sim.events FOR INSERT
  WITH CHECK (actor_id = (SELECT sim.current_actor_id()) AND sim.can_mutate_branch(world_id, branch_id));

ALTER TABLE cognition.mind_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.mind_states FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.observations FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.beliefs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.beliefs FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.memories FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.relationships FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.relationship_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.relationship_changes FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.runtime_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.runtime_assignments FORCE ROW LEVEL SECURITY;
ALTER TABLE cognition.decision_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.decision_traces FORCE ROW LEVEL SECURITY;

CREATE POLICY mind_states_access ON cognition.mind_states FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = mind_states.world_id
        AND entity.branch_id = mind_states.branch_id
        AND entity.id = mind_states.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
  )
  WITH CHECK (
    sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = mind_states.world_id
        AND entity.branch_id = mind_states.branch_id
        AND entity.id = mind_states.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  );

CREATE POLICY observations_access ON cognition.observations FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = observations.world_id
        AND entity.branch_id = observations.branch_id
        AND entity.id = observations.observer_entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
  )
  WITH CHECK (
    sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = observations.world_id
        AND entity.branch_id = observations.branch_id
        AND entity.id = observations.observer_entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  );

CREATE POLICY beliefs_access ON cognition.beliefs FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = beliefs.world_id
        AND entity.branch_id = beliefs.branch_id
        AND entity.id = beliefs.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
  )
  WITH CHECK (
    sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = beliefs.world_id
        AND entity.branch_id = beliefs.branch_id
        AND entity.id = beliefs.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  );

CREATE POLICY memories_access ON cognition.memories FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = memories.world_id
        AND entity.branch_id = memories.branch_id
        AND entity.id = memories.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
  )
  WITH CHECK (
    sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = memories.world_id
        AND entity.branch_id = memories.branch_id
        AND entity.id = memories.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  );

CREATE POLICY relationships_access ON cognition.relationships FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = relationships.world_id
        AND entity.branch_id = relationships.branch_id
        AND entity.id = relationships.source_entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
  )
  WITH CHECK (
    sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = relationships.world_id
        AND entity.branch_id = relationships.branch_id
        AND entity.id = relationships.source_entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  );

CREATE POLICY relationship_changes_access ON cognition.relationship_changes FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = relationship_changes.world_id
        AND entity.branch_id = relationship_changes.branch_id
        AND entity.id = relationship_changes.source_entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
  )
  WITH CHECK (
    actor_id = (SELECT sim.current_actor_id())
    AND (
      sim.has_world_capability(world_id, 'mind.write.all')
      OR EXISTS (
        SELECT 1 FROM sim.entities entity
        WHERE entity.world_id = relationship_changes.world_id
          AND entity.branch_id = relationship_changes.branch_id
          AND entity.id = relationship_changes.source_entity_id
          AND entity.controller_actor_id = (SELECT sim.current_actor_id())
      )
    )
  );

CREATE POLICY runtime_assignments_access ON cognition.runtime_assignments FOR ALL
  USING (
    sim.has_world_capability(world_id, 'mind.read.all')
    OR sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = runtime_assignments.world_id
        AND entity.branch_id = runtime_assignments.branch_id
        AND entity.id = runtime_assignments.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  )
  WITH CHECK (
    sim.has_world_capability(world_id, 'mind.write.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = runtime_assignments.world_id
        AND entity.branch_id = runtime_assignments.branch_id
        AND entity.id = runtime_assignments.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  );

CREATE POLICY decision_traces_access ON cognition.decision_traces FOR ALL
  USING (
    sim.has_world_capability(world_id, 'mind.read.all')
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = decision_traces.world_id
        AND entity.branch_id = decision_traces.branch_id
        AND entity.id = decision_traces.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
  )
  WITH CHECK (
    sim.can_mutate_branch(world_id, branch_id)
    AND (
      sim.has_world_capability(world_id, 'mind.write.all')
      OR EXISTS (
        SELECT 1 FROM sim.entities entity
        WHERE entity.world_id = decision_traces.world_id
          AND entity.branch_id = decision_traces.branch_id
          AND entity.id = decision_traces.entity_id
          AND entity.controller_actor_id = (SELECT sim.current_actor_id())
      )
    )
  );

ALTER TABLE experiments.telemetry_captures ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiments.telemetry_captures FORCE ROW LEVEL SECURITY;
CREATE POLICY telemetry_capture_access ON experiments.telemetry_captures FOR ALL
  USING (actor_id = (SELECT sim.current_actor_id()) OR sim.has_world_capability(world_id, 'metric.evaluate'))
  WITH CHECK (
    actor_id = (SELECT sim.current_actor_id())
    AND EXISTS (
      SELECT 1 FROM experiments.telemetry_settings settings
      WHERE settings.singleton AND settings.human_telemetry_enabled AND settings.local_only
    )
  );

GRANT USAGE ON SCHEMA infra_meta, sim, artifacts, persona, cognition, population, experiments TO tabletop_app;
GRANT SELECT ON infra_meta.schema_migrations TO tabletop_app;
GRANT SELECT ON ALL TABLES IN SCHEMA sim, artifacts, persona, cognition, population, experiments TO tabletop_app;
GRANT INSERT, UPDATE ON sim.worlds, sim.branches, sim.branch_projections, sim.runs,
  sim.interactions, sim.actors, sim.actor_roles, sim.actor_capabilities, sim.entities,
  sim.schedules, sim.outbox TO tabletop_app;
GRANT INSERT ON sim.snapshots TO tabletop_app;
GRANT DELETE ON sim.actor_roles, sim.actor_capabilities, sim.schedules TO tabletop_app;
GRANT INSERT ON sim.command_log, sim.events TO tabletop_app;
GRANT INSERT, UPDATE ON artifacts.objects TO tabletop_app;
GRANT INSERT, UPDATE ON persona.schema_versions, persona.entity_assignments TO tabletop_app;
GRANT INSERT ON persona.blueprints, persona.compiled_profiles TO tabletop_app;
GRANT INSERT, UPDATE ON cognition.mind_states, cognition.beliefs, cognition.relationships,
  cognition.runtime_assignments TO tabletop_app;
GRANT INSERT ON cognition.observations, cognition.memories,
  cognition.relationship_changes, cognition.decision_traces TO tabletop_app;
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA population TO tabletop_app;
GRANT INSERT, UPDATE ON experiments.scenarios, experiments.trials, experiments.jobs,
  experiments.comparisons, experiments.calibration_reports, experiments.telemetry_settings TO tabletop_app;
GRANT INSERT ON experiments.verifier_facts, experiments.metrics TO tabletop_app;
GRANT INSERT, DELETE ON experiments.telemetry_captures TO tabletop_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA sim, experiments TO tabletop_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA sim, artifacts, persona, cognition, population, experiments
  GRANT SELECT ON TABLES TO tabletop_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA sim, experiments
  GRANT USAGE, SELECT ON SEQUENCES TO tabletop_app;
