-- A source population record becomes immutable once embodied. Its live lifecycle
-- lives in the branch projection; inventory, health and needs live only on the body.
ALTER TABLE population.materialized_people
  ADD COLUMN binding_event_id uuid,
  ADD COLUMN binding_source_hash text,
  ADD CONSTRAINT population_binding_complete CHECK (
    (binding_event_id IS NULL AND binding_source_hash IS NULL)
    OR (entity_id IS NOT NULL AND binding_event_id IS NOT NULL AND binding_source_hash IS NOT NULL
        AND binding_source_hash ~ '^[0-9a-f]{64}$')
  ),
  ADD CONSTRAINT population_binding_event_scope
    FOREIGN KEY (world_id, branch_id, binding_event_id)
    REFERENCES sim.events(world_id, branch_id, event_id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX population_one_identity_per_body
  ON population.materialized_people(world_id, branch_id, entity_id)
  WHERE binding_event_id IS NOT NULL;

CREATE FUNCTION population.guard_embodied_source() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' AND OLD.binding_event_id IS NOT NULL THEN
    RAISE EXCEPTION 'embodied population source is immutable' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  IF NEW.binding_event_id IS NOT NULL THEN
    IF TG_OP <> 'UPDATE' THEN
      RAISE EXCEPTION 'binding requires a materialized source' USING ERRCODE = '23514';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['entity_id', 'binding_event_id', 'binding_source_hash'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['entity_id', 'binding_event_id', 'binding_source_hash']) THEN
      RAISE EXCEPTION 'binding cannot change source state' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM sim.events event
      JOIN sim.command_log command
        ON command.world_id = event.world_id AND command.branch_id = event.branch_id
       AND command.run_id = event.run_id AND command.actor_id = event.actor_id
       AND command.idempotency_key = event.idempotency_key
      WHERE event.event_id = NEW.binding_event_id
        AND event.world_id = NEW.world_id AND event.branch_id = NEW.branch_id
        AND event.event_type = 'tabletop.population.bind'
        AND command.command_type = 'tabletop.population.bind'
        AND command.parameters->>'population_id' = NEW.population_id::text
        AND event.payload->>'persona_id' = NEW.persona_id::text
        AND event.payload->>'entity_id' = NEW.entity_id::text
        AND (event.payload->>'version')::bigint = OLD.lifecycle_version + 1
    ) THEN
      RAISE EXCEPTION 'binding requires its committed scoped command event' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION population.guard_embodied_source() FROM PUBLIC;
CREATE TRIGGER population_embodied_source_guard
  BEFORE INSERT OR UPDATE OR DELETE ON population.materialized_people
  FOR EACH ROW EXECUTE FUNCTION population.guard_embodied_source();

CREATE FUNCTION population.guard_embodied_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- Serialize a stale lifecycle writer against first binding, not just a snapshot read.
  PERFORM 1 FROM population.materialized_people
    WHERE population_id = NEW.population_id AND persona_id = NEW.persona_id
    FOR UPDATE;
  IF EXISTS (SELECT 1 FROM population.materialized_people
             WHERE population_id = NEW.population_id AND persona_id = NEW.persona_id
               AND binding_event_id IS NOT NULL) THEN
    RAISE EXCEPTION 'embodied lifecycle requires canonical commands' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION population.guard_embodied_transition() FROM PUBLIC;
CREATE TRIGGER population_embodied_transition_guard
  BEFORE INSERT ON population.lifecycle_transitions
  FOR EACH ROW EXECUTE FUNCTION population.guard_embodied_transition();
