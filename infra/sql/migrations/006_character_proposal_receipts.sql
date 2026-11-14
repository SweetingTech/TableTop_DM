-- Uncommitted character-policy advice is operational provenance, never human
-- preference evidence or a sensory event. No canonical state changes here.
ALTER TABLE cognition.decision_traces ADD CONSTRAINT decision_traces_scope_identity
  UNIQUE (id, world_id, branch_id, run_id, entity_id);

CREATE TABLE cognition.character_proposal_receipts (
  decision_id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  character_id uuid NOT NULL,
  binding_id uuid NOT NULL,
  context_hash text NOT NULL CHECK (context_hash ~ '^[0-9a-f]{64}$'),
  projection_version bigint NOT NULL CHECK (projection_version >= 0),
  seed bigint NOT NULL CHECK (seed >= 0),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  created_at timestamptz NOT NULL,
  UNIQUE (world_id,branch_id,run_id,entity_id,actor_id,idempotency_key),
  FOREIGN KEY (world_id,branch_id,run_id,entity_id,character_id,binding_id)
    REFERENCES tabletop.character_bindings(world_id,branch_id,run_id,entity_id,character_id,binding_id) ON DELETE RESTRICT,
  FOREIGN KEY (decision_id,world_id,branch_id,run_id,entity_id)
    REFERENCES cognition.decision_traces(id,world_id,branch_id,run_id,entity_id) ON DELETE RESTRICT,
  CHECK (COALESCE(payload->>'decision_id' = decision_id::text, false)),
  CHECK (COALESCE(payload->>'actor_id' = actor_id::text, false)),
  CHECK (COALESCE(payload->>'idempotency_key' = idempotency_key, false)),
  CHECK (COALESCE(payload->>'binding_id' = binding_id::text, false)),
  CHECK (COALESCE(payload->>'character_id' = character_id::text, false)),
  CHECK (COALESCE(payload->>'context_hash' = context_hash, false)),
  CHECK (COALESCE(payload->>'projection_version' = projection_version::text, false)),
  CHECK (COALESCE(payload->>'seed' = seed::text, false)),
  CHECK (COALESCE(payload->'scope'->>'world_id' = world_id::text, false)),
  CHECK (COALESCE(payload->'scope'->>'branch_id' = branch_id::text, false)),
  CHECK (COALESCE(payload->'scope'->>'run_id' = run_id::text, false)),
  CHECK (COALESCE(payload->'scope'->>'entity_id' = entity_id::text, false)),
  CHECK (COALESCE(payload->>'authorship' = 'CHARACTER_POLICY', false)),
  CHECK (COALESCE(payload->>'execution_mode' = 'PROPOSAL_ONLY', false)),
  CHECK (COALESCE(payload->'committed' = 'false'::jsonb, false))
);

CREATE TRIGGER character_proposal_receipts_append_only BEFORE UPDATE OR DELETE
  ON cognition.character_proposal_receipts FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
ALTER TABLE cognition.character_proposal_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.character_proposal_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY character_proposal_receipts_read ON cognition.character_proposal_receipts FOR SELECT USING (
  sim.has_world_capability(world_id,'mind.read.all') OR (
    actor_id = sim.current_actor_id() AND EXISTS (
      SELECT 1 FROM sim.entities e WHERE (e.world_id,e.branch_id,e.id) =
        (character_proposal_receipts.world_id,character_proposal_receipts.branch_id,character_proposal_receipts.entity_id)
        AND e.controller_actor_id = sim.current_actor_id()
    )
  )
);
CREATE POLICY character_proposal_receipts_insert ON cognition.character_proposal_receipts FOR INSERT WITH CHECK (
  actor_id = sim.current_actor_id()
  AND sim.has_world_capability(world_id,'action.propose')
  AND sim.has_world_capability(world_id,'entity.act')
  AND sim.can_mutate_branch(world_id,branch_id)
  AND EXISTS (
    SELECT 1 FROM sim.entities e WHERE (e.world_id,e.branch_id,e.id) =
      (character_proposal_receipts.world_id,character_proposal_receipts.branch_id,character_proposal_receipts.entity_id)
      AND e.controller_actor_id = sim.current_actor_id()
  )
);
REVOKE ALL ON cognition.character_proposal_receipts FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT ON cognition.character_proposal_receipts TO tabletop_app;
