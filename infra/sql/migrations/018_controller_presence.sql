-- Presence can renew a private deadline. Authority changes still require a new epoch.
ALTER TABLE cognition.controller_assignments ADD CONSTRAINT controller_presence_shape CHECK (
  COALESCE(CASE WHEN payload ? 'disconnect_after_seconds' THEN
    (payload->>'disconnect_after_seconds')::integer BETWEEN 15 AND 600
    AND ((payload->>'mode'='HUMAN') = (payload ? 'presence_deadline_at'))
    AND (NOT (payload ? 'presence_deadline_at') OR
      (payload->>'presence_deadline_at')::timestamptz IS NOT NULL)
  ELSE NOT (payload ? 'presence_deadline_at') END, false)
  AND (NOT (payload ? 'handoff_reason') OR COALESCE(
    payload->>'handoff_reason'='DISCONNECT_TIMEOUT'
    AND payload->>'mode' IN ('AUTONOMOUS','PAUSED')
    AND (payload ? 'disconnect_after_seconds'), false))
);

CREATE OR REPLACE FUNCTION cognition.guard_controller_update() RETURNS trigger
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
  ELSIF (NEW.payload->>'epoch')::bigint = (OLD.payload->>'epoch')::bigint THEN
    IF NOT COALESCE(
      sim.current_actor_id()=OLD.owner_actor_id AND OLD.payload->>'mode'='HUMAN'
      AND (NEW.payload - 'presence_deadline_at') = (OLD.payload - 'presence_deadline_at')
      AND (NEW.payload->>'presence_deadline_at')::timestamptz >
          (OLD.payload->>'presence_deadline_at')::timestamptz
      AND (NEW.payload->>'presence_deadline_at')::timestamptz <= clock_timestamp()
          + make_interval(secs => (OLD.payload->>'disconnect_after_seconds')::integer), false)
    THEN RAISE EXCEPTION 'same-epoch update must only renew owner presence'; END IF;
  ELSIF (NEW.payload->>'epoch')::bigint <> (OLD.payload->>'epoch')::bigint+1 THEN
    RAISE EXCEPTION 'handoff must increment controller epoch';
  END IF;
  RETURN NEW;
END $$;
