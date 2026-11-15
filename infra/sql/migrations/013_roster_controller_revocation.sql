-- Removing a human seat must also revoke runtime-owner read/control delegation.
-- Keep the immutable controller owner and append-only handoff history for rejoining.
CREATE OR REPLACE FUNCTION sim.runtime_controls_entity(w uuid,b uuid,e uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path=pg_catalog,cognition,sim AS $$
  SELECT EXISTS (SELECT 1 FROM cognition.controller_assignments c
    WHERE (c.world_id,c.branch_id,c.entity_id)=(w,b,e)
    AND EXISTS (SELECT 1 FROM sim.actors a WHERE a.id=sim.current_actor_id() AND a.is_active)
    AND ((c.executor_actor_id=sim.current_actor_id() AND c.payload->>'mode'='AUTONOMOUS')
      OR (c.owner_actor_id=sim.current_actor_id()
        AND c.payload->>'last_error' IS DISTINCT FROM 'seat_removed')))
$$;
REVOKE ALL ON FUNCTION sim.runtime_controls_entity(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.runtime_controls_entity(uuid,uuid,uuid) TO tabletop_app;

-- A retained historical owner cannot resume a removed seat through direct runtime SQL.
DROP POLICY controller_update ON cognition.controller_assignments;
CREATE POLICY controller_update ON cognition.controller_assignments FOR UPDATE USING (
  sim.has_world_capability(world_id,'mind.write.all')
  OR (sim.current_actor_id()=owner_actor_id AND sim.runtime_controls_entity(world_id,branch_id,entity_id))
  OR (sim.current_actor_id()=executor_actor_id AND payload->>'mode'='AUTONOMOUS')
) WITH CHECK (
  sim.has_world_capability(world_id,'mind.write.all')
  OR (sim.current_actor_id()=owner_actor_id AND sim.runtime_controls_entity(world_id,branch_id,entity_id))
  OR (sim.current_actor_id()=executor_actor_id AND payload->>'mode' IN ('AUTONOMOUS','PAUSED'))
);

DROP POLICY handoff_insert ON cognition.controller_handoffs;
CREATE POLICY handoff_insert ON cognition.controller_handoffs FOR INSERT WITH CHECK (
  actor_id=sim.current_actor_id() AND EXISTS (
    SELECT 1 FROM cognition.controller_assignments c WHERE
      (c.world_id,c.branch_id,c.run_id,c.entity_id)=
      (controller_handoffs.world_id,controller_handoffs.branch_id,controller_handoffs.run_id,controller_handoffs.entity_id)
      AND (sim.has_world_capability(c.world_id,'mind.write.all')
        OR (c.owner_actor_id=sim.current_actor_id() AND sim.runtime_controls_entity(c.world_id,c.branch_id,c.entity_id)))
  )
);
