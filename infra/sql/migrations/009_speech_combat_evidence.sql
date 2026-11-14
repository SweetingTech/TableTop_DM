-- Additional decision types have their own versioned evidence; 008 remains immutable.
CREATE TABLE cognition.human_choice_evidence (
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
    AND payload->>'binding_id'=binding_id::text AND payload->>'version'='speech-combat-behavior-1.0.0'
    AND (payload->>'projection_version')::bigint>=0
    AND jsonb_typeof(payload->'frame')='object'
    AND jsonb_typeof(payload->'options')='array'
    AND jsonb_array_length(payload->'options') BETWEEN 1 AND 28
    AND length(payload->>'chosen_key') BETWEEN 1 AND 100,false))
);
CREATE INDEX human_choice_scope ON cognition.human_choice_evidence(world_id,branch_id,run_id,entity_id,sequence DESC);
ALTER TABLE cognition.human_choice_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.human_choice_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY human_choice_read ON cognition.human_choice_evidence FOR SELECT USING (
  player_actor_id=sim.current_actor_id() OR sim.runtime_controls_entity(world_id,branch_id,entity_id)
  OR sim.has_world_capability(world_id,'mind.read.all')
);
CREATE POLICY human_choice_insert ON cognition.human_choice_evidence FOR INSERT WITH CHECK (
  player_actor_id=sim.current_actor_id() AND sim.can_mutate_branch(world_id,branch_id)
  AND EXISTS (SELECT 1 FROM sim.entities e WHERE
    (e.world_id,e.branch_id,e.id)=(human_choice_evidence.world_id,human_choice_evidence.branch_id,human_choice_evidence.entity_id)
    AND e.controller_actor_id=sim.current_actor_id())
);
CREATE FUNCTION cognition.guard_human_choice() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim,cognition AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM sim.events e JOIN sim.command_log c
      ON (c.run_id,c.actor_id,c.idempotency_key)=(e.run_id,e.actor_id,e.idempotency_key)
    JOIN sim.actors a ON a.id=e.actor_id
    JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(e.world_id,e.branch_id,e.run_id)
    JOIN sim.branches b ON (b.world_id,b.id)=(e.world_id,e.branch_id)
    WHERE (e.world_id,e.branch_id,e.run_id,e.embodied_entity_id,e.actor_id,e.event_id)=
      (NEW.world_id,NEW.branch_id,NEW.run_id,NEW.entity_id,NEW.player_actor_id,NEW.event_id)
      AND e.decision_trace_id IS NULL AND c.decision_authorship='HUMAN'
      AND c.input_origin='HUMAN_INPUT' AND a.actor_kind='HUMAN'
      AND r.run_kind='LIVE' AND b.branch_kind='CANONICAL'
      AND ((c.command_type='tabletop.combat.attack' AND NEW.payload->>'chosen_key'='attack:'||(c.parameters->>'target_id'))
        OR (c.command_type='tabletop.spatial.move' AND NEW.payload->>'chosen_key'='move:'||(c.parameters->>'dx')||','||(c.parameters->>'dy'))
        OR (c.command_type='tabletop.dialogue.speak' AND c.parameters->>'language'='common'
            AND NEW.payload->>'chosen_key' LIKE 'speech:%:'||(c.parameters->>'volume')))
  ) THEN RAISE EXCEPTION 'choice evidence requires a matching committed human action'; END IF;
  IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.payload->'options') o WHERE o->>'key'=NEW.payload->>'chosen_key')
  THEN RAISE EXCEPTION 'chosen action is absent from perceived options'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER human_choice_source BEFORE INSERT ON cognition.human_choice_evidence
  FOR EACH ROW EXECUTE FUNCTION cognition.guard_human_choice();
CREATE TRIGGER human_choice_append_only BEFORE UPDATE OR DELETE ON cognition.human_choice_evidence
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
REVOKE ALL ON cognition.human_choice_evidence FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT ON cognition.human_choice_evidence TO tabletop_app;
GRANT USAGE,SELECT ON SEQUENCE cognition.human_choice_evidence_sequence_seq TO tabletop_app;
REVOKE ALL ON FUNCTION cognition.guard_human_choice() FROM PUBLIC;
