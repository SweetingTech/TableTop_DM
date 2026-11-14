-- Input origin is independent of execution authority. Old commands are not training evidence.
ALTER TABLE sim.command_log ADD COLUMN input_origin text NOT NULL DEFAULT 'UNSPECIFIED'
  CHECK (input_origin IN ('UNSPECIFIED','HUMAN_INPUT','POLICY_ADVICE','OPERATOR'));

CREATE TABLE cognition.human_movement_evidence (
  sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  event_id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  player_actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  character_id uuid NOT NULL,
  binding_id uuid NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
  FOREIGN KEY (world_id,branch_id,event_id) REFERENCES sim.events(world_id,branch_id,event_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,run_id,entity_id,character_id,binding_id)
    REFERENCES tabletop.character_bindings(world_id,branch_id,run_id,entity_id,character_id,binding_id) ON DELETE RESTRICT,
  CHECK (COALESCE(payload->>'world_id'=world_id::text AND payload->>'branch_id'=branch_id::text
    AND payload->>'run_id'=run_id::text AND payload->>'entity_id'=entity_id::text
    AND payload->>'player_actor_id'=player_actor_id::text AND payload->>'character_id'=character_id::text
    AND payload->>'binding_id'=binding_id::text AND payload->>'version'='movement-behavior-1.0.0'
    AND payload->>'chosen' IN ('north','east','south','west')
    AND (payload->>'projection_version')::bigint>=0
    AND jsonb_typeof(payload#>'{frame,injured}')='boolean'
    AND (payload#>>'{frame,company}')::integer BETWEEN 0 AND 2
    AND jsonb_typeof(payload#>'{frame,zone}')='string'
    AND jsonb_array_length(payload#>'{frame,options}')=4, false))
);
CREATE INDEX human_movement_scope ON cognition.human_movement_evidence
  (world_id,branch_id,run_id,entity_id,sequence DESC);
ALTER TABLE cognition.human_movement_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.human_movement_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY human_movement_read ON cognition.human_movement_evidence FOR SELECT USING (
  player_actor_id=sim.current_actor_id() OR sim.runtime_controls_entity(world_id,branch_id,entity_id)
  OR sim.has_world_capability(world_id,'mind.read.all')
);
CREATE POLICY human_movement_insert ON cognition.human_movement_evidence FOR INSERT WITH CHECK (
  player_actor_id=sim.current_actor_id() AND sim.can_mutate_branch(world_id,branch_id)
  AND EXISTS (SELECT 1 FROM sim.entities e WHERE
    (e.world_id,e.branch_id,e.id)=(human_movement_evidence.world_id,human_movement_evidence.branch_id,human_movement_evidence.entity_id)
    AND e.controller_actor_id=sim.current_actor_id())
);
CREATE FUNCTION cognition.guard_human_movement() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim,cognition AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM sim.events e JOIN sim.command_log c
      ON (c.run_id,c.actor_id,c.idempotency_key)=(e.run_id,e.actor_id,e.idempotency_key)
    JOIN sim.actors a ON a.id=e.actor_id
    JOIN sim.runs r ON r.id=e.run_id AND r.world_id=e.world_id AND r.branch_id=e.branch_id
    JOIN sim.branches b ON b.id=e.branch_id AND b.world_id=e.world_id
    WHERE e.event_id=NEW.event_id AND e.world_id=NEW.world_id AND e.branch_id=NEW.branch_id
      AND e.run_id=NEW.run_id AND e.embodied_entity_id=NEW.entity_id
      AND e.actor_id=NEW.player_actor_id AND e.decision_trace_id IS NULL
      AND c.command_type='tabletop.spatial.move' AND c.decision_authorship='HUMAN'
      AND c.input_origin='HUMAN_INPUT' AND a.actor_kind='HUMAN'
      AND r.run_kind='LIVE' AND b.branch_kind='CANONICAL'
  ) THEN RAISE EXCEPTION 'human evidence requires a matching committed human movement'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.payload#>'{frame,options}') o
    WHERE NOT COALESCE(o->>'direction' IN ('north','east','south','west')
      AND (o->>'approach')::numeric BETWEEN -1 AND 1,false))
    OR (SELECT count(DISTINCT o->>'direction') FROM jsonb_array_elements(NEW.payload#>'{frame,options}') o)<>4
  THEN RAISE EXCEPTION 'invalid movement options'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER human_movement_source BEFORE INSERT ON cognition.human_movement_evidence
  FOR EACH ROW EXECUTE FUNCTION cognition.guard_human_movement();
CREATE TRIGGER human_movement_append_only BEFORE UPDATE OR DELETE ON cognition.human_movement_evidence
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
REVOKE ALL ON cognition.human_movement_evidence FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT ON cognition.human_movement_evidence TO tabletop_app;
GRANT USAGE,SELECT ON SEQUENCE cognition.human_movement_evidence_sequence_seq TO tabletop_app;
REVOKE ALL ON FUNCTION cognition.guard_human_movement() FROM PUBLIC;
