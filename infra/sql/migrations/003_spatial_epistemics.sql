-- Spatial epistemics: frozen entity-level perception and subjective evidence.
-- Canonical event authorization remains in sim.events.visible_to.

CREATE TABLE sim.event_perceptions (
  event_id uuid NOT NULL,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  observer_entity_id uuid NOT NULL,
  controller_actor_id uuid REFERENCES sim.actors(id) ON DELETE SET NULL,
  modalities text[] NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('DIRECT', 'PARTIAL')),
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  allowed_payload_fields text[],
  hidden_payload_fields text[] NOT NULL DEFAULT '{}',
  payload_overrides jsonb NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(payload_overrides) = 'object'),
  reason_codes text[] NOT NULL DEFAULT '{}',
  resolver_version text NOT NULL CHECK (length(btrim(resolver_version)) BETWEEN 1 AND 120),
  spatial_context_hash text NOT NULL CHECK (spatial_context_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, observer_entity_id),
  FOREIGN KEY (world_id, branch_id, event_id)
    REFERENCES sim.events(world_id, branch_id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, observer_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  CHECK (cardinality(modalities) > 0),
  CHECK (modalities <@ ARRAY['SIGHT','SOUND','TOUCH','MAGIC']::text[])
);
CREATE INDEX idx_sim_event_perceptions_observer
  ON sim.event_perceptions(world_id, branch_id, observer_entity_id, created_at DESC);
CREATE INDEX idx_sim_event_perceptions_controller
  ON sim.event_perceptions(world_id, controller_actor_id, created_at DESC)
  WHERE controller_actor_id IS NOT NULL;
CREATE TRIGGER sim_event_perceptions_append_only
  BEFORE UPDATE OR DELETE ON sim.event_perceptions
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

ALTER TABLE cognition.observations
  ADD CONSTRAINT cognition_observations_world_branch_id_unique
  UNIQUE (world_id, branch_id, id);
ALTER TABLE cognition.beliefs
  ADD CONSTRAINT cognition_beliefs_world_branch_id_unique
  UNIQUE (world_id, branch_id, id);
ALTER TABLE cognition.memories
  ADD COLUMN source_observation_id uuid
    REFERENCES cognition.observations(id) ON DELETE SET NULL;

CREATE TABLE cognition.belief_evidence (
  id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  belief_id uuid,
  source_observation_id uuid NOT NULL,
  evidence_type text NOT NULL CHECK (
    evidence_type IN ('DIRECT_OBSERVATION','TESTIMONY','DOCUMENT','INFERENCE','MAGIC')
  ),
  immediate_source_entity_id uuid,
  claimed_origin_event_id uuid,
  parent_evidence_id uuid REFERENCES cognition.belief_evidence(id) ON DELETE RESTRICT,
  direct_witness boolean NOT NULL,
  confidence_modifier numeric(5,4) NOT NULL CHECK (confidence_modifier BETWEEN 0 AND 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, branch_id, id),
  FOREIGN KEY (world_id, branch_id, entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE CASCADE,
  FOREIGN KEY (belief_id)
    REFERENCES cognition.beliefs(id) ON DELETE SET NULL,
  FOREIGN KEY (world_id, branch_id, source_observation_id)
    REFERENCES cognition.observations(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, immediate_source_entity_id)
    REFERENCES sim.entities(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (claimed_origin_event_id)
    REFERENCES sim.events(event_id) ON DELETE SET NULL
);
CREATE INDEX idx_cognition_belief_evidence_entity
  ON cognition.belief_evidence(world_id, branch_id, entity_id, created_at DESC);
CREATE INDEX idx_cognition_belief_evidence_belief
  ON cognition.belief_evidence(world_id, branch_id, belief_id, created_at DESC)
  WHERE belief_id IS NOT NULL;
CREATE TRIGGER cognition_belief_evidence_append_only
  BEFORE UPDATE OR DELETE ON cognition.belief_evidence
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

ALTER TABLE sim.event_perceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.event_perceptions FORCE ROW LEVEL SECURITY;
CREATE OR REPLACE FUNCTION sim.can_append_event_perception(
  target_world_id uuid,
  target_branch_id uuid,
  target_event_id uuid
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, sim
AS $$
  SELECT EXISTS (
      SELECT 1
      FROM sim.branches branch
      JOIN sim.actor_capabilities capability
        ON capability.world_id = branch.world_id
       AND capability.actor_id = nullif(current_setting('app.actor_id', true), '')::uuid
       AND capability.capability = CASE
         WHEN branch.branch_kind = 'CANONICAL' THEN 'action.commit'
         ELSE 'action.propose'
       END
      WHERE branch.world_id = target_world_id
        AND branch.id = target_branch_id
        AND branch.status = 'ACTIVE'
    )
    AND EXISTS (
      SELECT 1 FROM sim.events event
      WHERE event.world_id = target_world_id
        AND event.branch_id = target_branch_id
        AND event.event_id = target_event_id
        AND event.actor_id = nullif(current_setting('app.actor_id', true), '')::uuid
    )
$$;
REVOKE ALL ON FUNCTION sim.can_append_event_perception(uuid, uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.can_append_event_perception(uuid, uuid, uuid) TO tabletop_app;
CREATE POLICY event_perceptions_read ON sim.event_perceptions FOR SELECT
  USING (
    controller_actor_id = (SELECT sim.current_actor_id())
    OR EXISTS (
      SELECT 1 FROM sim.events event
      WHERE event.world_id = event_perceptions.world_id
        AND event.branch_id = event_perceptions.branch_id
        AND event.event_id = event_perceptions.event_id
        AND event.actor_id = (SELECT sim.current_actor_id())
    )
    OR EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = event_perceptions.world_id
        AND entity.branch_id = event_perceptions.branch_id
        AND entity.id = event_perceptions.observer_entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'world.read.all')
    OR sim.has_world_capability(world_id, 'mind.read.all')
  );
CREATE POLICY event_perceptions_insert ON sim.event_perceptions FOR INSERT
  WITH CHECK (
    sim.can_append_event_perception(world_id, branch_id, event_id)
  );

ALTER TABLE cognition.belief_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.belief_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY belief_evidence_read ON cognition.belief_evidence FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = belief_evidence.world_id
        AND entity.branch_id = belief_evidence.branch_id
        AND entity.id = belief_evidence.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.read.all')
  );
CREATE POLICY belief_evidence_insert ON cognition.belief_evidence FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM sim.entities entity
      WHERE entity.world_id = belief_evidence.world_id
        AND entity.branch_id = belief_evidence.branch_id
        AND entity.id = belief_evidence.entity_id
        AND entity.controller_actor_id = (SELECT sim.current_actor_id())
    )
    OR sim.has_world_capability(world_id, 'mind.write.all')
  );

GRANT SELECT, INSERT ON sim.event_perceptions TO tabletop_app;
GRANT SELECT, INSERT ON cognition.belief_evidence TO tabletop_app;
