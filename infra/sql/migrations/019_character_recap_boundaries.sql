-- Newly committed commands retain their exact resulting branch revision for private recap bounds.
ALTER TABLE sim.command_log ADD COLUMN committed_revision bigint CHECK (committed_revision >= 1);
CREATE UNIQUE INDEX command_log_committed_revision
  ON sim.command_log (world_id,branch_id,committed_revision) WHERE committed_revision IS NOT NULL;

CREATE FUNCTION sim.stamp_committed_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim AS $$
BEGIN
  SELECT p.version INTO NEW.committed_revision FROM sim.branch_projections p
  WHERE (p.world_id,p.branch_id)=(NEW.world_id,NEW.branch_id);
  IF NEW.committed_revision IS NULL THEN
    RAISE EXCEPTION 'command requires a committed branch revision';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER command_log_revision_before_insert BEFORE INSERT ON sim.command_log
  FOR EACH ROW EXECUTE FUNCTION sim.stamp_committed_revision();
REVOKE ALL ON FUNCTION sim.stamp_committed_revision() FROM PUBLIC;

DROP POLICY handoff_read ON cognition.controller_handoffs;
CREATE POLICY handoff_read ON cognition.controller_handoffs FOR SELECT USING (
  actor_id=sim.current_actor_id() OR sim.has_world_capability(world_id,'mind.read.all')
  OR (sim.has_world_capability(world_id,'world.read') AND EXISTS (
    SELECT 1 FROM sim.entities e
    WHERE (e.world_id,e.branch_id,e.id)=(
      controller_handoffs.world_id,controller_handoffs.branch_id,controller_handoffs.entity_id)
    AND e.controller_actor_id=sim.current_actor_id()
  ))
);
