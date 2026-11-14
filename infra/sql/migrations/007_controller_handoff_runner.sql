-- Operational controllers and scheduling are private, separate from sensory truth.
CREATE TABLE cognition.controller_assignments (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  owner_actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  executor_actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  PRIMARY KEY (world_id,branch_id,run_id,entity_id),
  FOREIGN KEY (world_id,branch_id,run_id) REFERENCES sim.runs(world_id,branch_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,entity_id) REFERENCES sim.entities(world_id,branch_id,id) ON DELETE RESTRICT,
  CHECK (COALESCE(payload->>'world_id'=world_id::text AND payload->>'branch_id'=branch_id::text
    AND payload->>'run_id'=run_id::text AND payload->>'entity_id'=entity_id::text
    AND payload->>'owner_actor_id'=owner_actor_id::text
    AND payload->>'executor_actor_id'=executor_actor_id::text, false)),
  CHECK (COALESCE(payload->>'mode' IN ('HUMAN','AUTONOMOUS','PAUSED'), false)),
  CHECK ((payload->>'next_due')::timestamptz IS NOT NULL),
  CHECK (COALESCE((payload->>'epoch')::bigint>=1 AND (payload->>'step')::bigint>=0
    AND (payload->>'max_steps')::bigint BETWEEN 1 AND 1000
    AND (payload->>'step')::bigint <= (payload->>'max_steps')::bigint
    AND (payload->>'interval_ms')::integer BETWEEN 100 AND 60000
    AND (payload->>'failures')::integer>=0, false))
);
ALTER TABLE cognition.controller_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.controller_assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY controller_read ON cognition.controller_assignments FOR SELECT USING (
  sim.current_actor_id() IN (owner_actor_id,executor_actor_id)
  OR sim.has_world_capability(world_id,'mind.read.all')
  OR sim.has_world_capability(world_id,'mind.write.all')
);
CREATE POLICY controller_insert ON cognition.controller_assignments FOR INSERT WITH CHECK (
  sim.can_mutate_branch(world_id,branch_id) AND (
    sim.has_world_capability(world_id,'mind.write.all') OR EXISTS (
      SELECT 1 FROM sim.entities e WHERE (e.world_id,e.branch_id,e.id)=
        (controller_assignments.world_id,controller_assignments.branch_id,controller_assignments.entity_id)
        AND e.controller_actor_id=sim.current_actor_id() AND e.controller_actor_id=owner_actor_id
    )
  )
);
CREATE POLICY controller_update ON cognition.controller_assignments FOR UPDATE USING (
  sim.current_actor_id()=owner_actor_id OR sim.has_world_capability(world_id,'mind.write.all')
  OR (sim.current_actor_id()=executor_actor_id AND payload->>'mode'='AUTONOMOUS')
) WITH CHECK (
  sim.current_actor_id() IN (owner_actor_id,executor_actor_id)
  OR sim.has_world_capability(world_id,'mind.write.all')
);
CREATE FUNCTION cognition.guard_controller_update() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,cognition,sim AS $$
BEGIN
  IF NEW.owner_actor_id IS DISTINCT FROM OLD.owner_actor_id
    OR NEW.executor_actor_id IS DISTINCT FROM OLD.executor_actor_id
    OR (NEW.world_id,NEW.branch_id,NEW.run_id,NEW.entity_id) IS DISTINCT FROM
       (OLD.world_id,OLD.branch_id,OLD.run_id,OLD.entity_id) THEN
    RAISE EXCEPTION 'controller identity is immutable';
  END IF;
  IF sim.current_actor_id()=OLD.executor_actor_id THEN
    IF OLD.payload->>'mode'<>'AUTONOMOUS' OR
       NEW.payload->>'mode' NOT IN ('AUTONOMOUS','PAUSED') OR
       (NEW.payload - ARRAY['step','mode','last_error','next_due','failures']) IS DISTINCT FROM
       (OLD.payload - ARRAY['step','mode','last_error','next_due','failures']) OR
       (NEW.payload->>'step')::bigint NOT BETWEEN (OLD.payload->>'step')::bigint AND (OLD.payload->>'step')::bigint+1
    THEN RAISE EXCEPTION 'executor cannot change controller authority'; END IF;
  ELSIF (NEW.payload->>'epoch')::bigint <> (OLD.payload->>'epoch')::bigint+1 THEN
    RAISE EXCEPTION 'handoff must increment controller epoch';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER controller_update_guard BEFORE UPDATE ON cognition.controller_assignments
  FOR EACH ROW EXECUTE FUNCTION cognition.guard_controller_update();
REVOKE ALL ON FUNCTION cognition.guard_controller_update() FROM PUBLIC;
REVOKE ALL ON cognition.controller_assignments FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT,UPDATE ON cognition.controller_assignments TO tabletop_app;

CREATE FUNCTION cognition.guard_controller_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,cognition,sim AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM sim.actors a WHERE a.id=NEW.executor_actor_id AND a.actor_kind='AGENT') THEN
    RAISE EXCEPTION 'controller executor must be an agent';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM cognition.controller_assignments c WHERE
    (c.world_id,c.branch_id,c.run_id,c.entity_id)=(NEW.world_id,NEW.branch_id,NEW.run_id,NEW.entity_id))
    AND (NEW.payload->>'epoch')::bigint <> 1 THEN
    RAISE EXCEPTION 'initial controller epoch must be one';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM sim.runs r JOIN sim.branches b
    ON (b.world_id,b.id)=(r.world_id,r.branch_id)
    WHERE (r.world_id,r.branch_id,r.id)=(NEW.world_id,NEW.branch_id,NEW.run_id)
      AND r.run_kind='LIVE' AND b.branch_kind='CANONICAL') THEN
    RAISE EXCEPTION 'controllers require a canonical live run';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER controller_insert_guard BEFORE INSERT ON cognition.controller_assignments
  FOR EACH ROW EXECUTE FUNCTION cognition.guard_controller_insert();
REVOKE ALL ON FUNCTION cognition.guard_controller_insert() FROM PUBLIC;

CREATE TABLE cognition.controller_handoffs (
  receipt_id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id,branch_id,run_id,entity_id,actor_id,idempotency_key),
  FOREIGN KEY (world_id,branch_id,run_id,entity_id)
    REFERENCES cognition.controller_assignments(world_id,branch_id,run_id,entity_id) ON DELETE RESTRICT,
  CHECK (COALESCE(payload->>'actor_id'=actor_id::text AND
    payload->>'idempotency_key'=idempotency_key AND payload->'sensory_event'='false'::jsonb
    AND payload->'state'->>'world_id'=world_id::text
    AND payload->'state'->>'branch_id'=branch_id::text
    AND payload->'state'->>'run_id'=run_id::text
    AND payload->'state'->>'entity_id'=entity_id::text, false))
);
CREATE TRIGGER controller_handoffs_append_only BEFORE UPDATE OR DELETE ON cognition.controller_handoffs
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
ALTER TABLE cognition.controller_handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.controller_handoffs FORCE ROW LEVEL SECURITY;
CREATE POLICY handoff_read ON cognition.controller_handoffs FOR SELECT USING (
  actor_id=sim.current_actor_id() OR sim.has_world_capability(world_id,'mind.read.all')
);
CREATE POLICY handoff_insert ON cognition.controller_handoffs FOR INSERT WITH CHECK (
  actor_id=sim.current_actor_id() AND EXISTS (
    SELECT 1 FROM cognition.controller_assignments c WHERE
      (c.world_id,c.branch_id,c.run_id,c.entity_id)=
      (controller_handoffs.world_id,controller_handoffs.branch_id,controller_handoffs.run_id,controller_handoffs.entity_id)
      AND (c.owner_actor_id=sim.current_actor_id() OR sim.has_world_capability(c.world_id,'mind.write.all'))
  )
);
REVOKE ALL ON cognition.controller_handoffs FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT ON cognition.controller_handoffs TO tabletop_app;

CREATE FUNCTION sim.runtime_controls_entity(w uuid,b uuid,e uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,cognition,sim AS $$
  SELECT EXISTS (SELECT 1 FROM cognition.controller_assignments c WHERE
    (c.world_id,c.branch_id,c.entity_id)=(w,b,e)
    AND EXISTS (SELECT 1 FROM sim.actors a WHERE a.id=sim.current_actor_id() AND a.is_active)
    AND ((c.executor_actor_id=sim.current_actor_id() AND c.payload->>'mode'='AUTONOMOUS')
         OR c.owner_actor_id=sim.current_actor_id()))
$$;
REVOKE ALL ON FUNCTION sim.runtime_controls_entity(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.runtime_controls_entity(uuid,uuid,uuid) TO tabletop_app;

CREATE POLICY runtime_entity_read ON sim.entities FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,id));

CREATE POLICY runtime_mind_read ON cognition.mind_states FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,entity_id));
CREATE POLICY runtime_observation_read ON cognition.observations FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,observer_entity_id));
CREATE POLICY runtime_belief_read ON cognition.beliefs FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,entity_id));
CREATE POLICY runtime_memory_read ON cognition.memories FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,entity_id));
CREATE POLICY runtime_relationship_read ON cognition.relationships FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,source_entity_id));
CREATE POLICY runtime_binding_read ON tabletop.character_bindings FOR SELECT
  USING (sim.runtime_controls_entity(world_id,branch_id,entity_id));
CREATE POLICY runtime_card_read ON tabletop.character_card_revisions FOR SELECT USING (
  EXISTS (SELECT 1 FROM tabletop.character_bindings b WHERE b.character_id=character_card_revisions.character_id
    AND b.card_revision_id=character_card_revisions.revision_id
    AND sim.runtime_controls_entity(b.world_id,b.branch_id,b.entity_id))
);
CREATE POLICY runtime_trace_access ON cognition.decision_traces FOR ALL
  USING (sim.runtime_controls_entity(world_id,branch_id,entity_id))
  WITH CHECK (sim.runtime_controls_entity(world_id,branch_id,entity_id) AND sim.can_mutate_branch(world_id,branch_id));
CREATE POLICY runtime_proposal_read ON cognition.character_proposal_receipts FOR SELECT
  USING (actor_id=sim.current_actor_id() AND sim.runtime_controls_entity(world_id,branch_id,entity_id));
CREATE POLICY runtime_proposal_insert ON cognition.character_proposal_receipts FOR INSERT WITH CHECK (
  actor_id=sim.current_actor_id() AND sim.runtime_controls_entity(world_id,branch_id,entity_id)
  AND sim.has_world_capability(world_id,'action.propose') AND sim.has_world_capability(world_id,'entity.act')
  AND sim.can_mutate_branch(world_id,branch_id)
);

ALTER TABLE sim.command_log ADD COLUMN control_epoch bigint CHECK (control_epoch>=1),
  ADD COLUMN control_step bigint CHECK (control_step>=0),
  ADD COLUMN decision_authorship text NOT NULL DEFAULT 'HUMAN'
    CHECK (decision_authorship IN ('HUMAN','CHARACTER_POLICY'));
ALTER TABLE sim.command_log ADD CHECK (control_step IS NULL OR
  (control_epoch IS NOT NULL AND decision_authorship='CHARACTER_POLICY'));
