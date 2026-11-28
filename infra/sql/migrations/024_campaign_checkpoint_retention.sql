-- Operator retention changes and retired manifests remain available for audit.
ALTER TABLE sim.campaign_checkpoints
  ADD UNIQUE (world_id, branch_id, checkpoint_id);

CREATE TABLE sim.campaign_checkpoint_retention (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  policy_id uuid NOT NULL,
  revision bigint NOT NULL CHECK (revision > 0),
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  keep_automatic integer CHECK (keep_automatic BETWEEN 1 AND 1000),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (world_id, branch_id, policy_id),
  UNIQUE (world_id, branch_id, revision),
  FOREIGN KEY (world_id, branch_id) REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT
);

CREATE TABLE sim.campaign_checkpoint_retention_state (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  status text NOT NULL CHECK (status IN ('AVAILABLE', 'PINNED', 'RETIRED')),
  policy_id uuid,
  changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (world_id, branch_id, checkpoint_id),
  FOREIGN KEY (world_id, branch_id, checkpoint_id)
    REFERENCES sim.campaign_checkpoints(world_id, branch_id, checkpoint_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, policy_id)
    REFERENCES sim.campaign_checkpoint_retention(world_id, branch_id, policy_id) ON DELETE RESTRICT,
  CHECK ((status = 'RETIRED') = (policy_id IS NOT NULL))
);

CREATE TRIGGER campaign_checkpoint_retention_append_only
  BEFORE UPDATE OR DELETE ON sim.campaign_checkpoint_retention
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

ALTER TABLE sim.campaign_checkpoint_retention ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_checkpoint_retention FORCE ROW LEVEL SECURITY;
CREATE POLICY checkpoint_retention_read ON sim.campaign_checkpoint_retention
  FOR SELECT USING (sim.can_read_campaign_checkpoint(world_id));
CREATE POLICY checkpoint_retention_add ON sim.campaign_checkpoint_retention
  FOR INSERT WITH CHECK (
    actor_id = (SELECT sim.current_actor_id()) AND sim.can_read_campaign_checkpoint(world_id)
    AND EXISTS (
      SELECT 1 FROM sim.branches b
      WHERE (b.world_id,b.id)=(campaign_checkpoint_retention.world_id,campaign_checkpoint_retention.branch_id)
        AND b.branch_kind='CANONICAL' AND b.status='ACTIVE'
    )
  );

ALTER TABLE sim.campaign_checkpoint_retention_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_checkpoint_retention_state FORCE ROW LEVEL SECURITY;
CREATE POLICY checkpoint_retention_state_read ON sim.campaign_checkpoint_retention_state
  FOR SELECT USING (sim.can_read_campaign_checkpoint(world_id));
CREATE POLICY checkpoint_retention_state_insert ON sim.campaign_checkpoint_retention_state
  FOR INSERT WITH CHECK (
    actor_id = (SELECT sim.current_actor_id()) AND sim.can_read_campaign_checkpoint(world_id)
  );
CREATE POLICY checkpoint_retention_state_update ON sim.campaign_checkpoint_retention_state
  FOR UPDATE USING (status <> 'RETIRED' AND sim.can_read_campaign_checkpoint(world_id))
  WITH CHECK (
    actor_id = (SELECT sim.current_actor_id()) AND sim.can_read_campaign_checkpoint(world_id)
  );

CREATE FUNCTION sim.guard_checkpoint_retirement() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, sim AS $$
DECLARE
  keep_count integer;
  current_policy uuid;
  newer_count bigint;
BEGIN
  IF NEW.status = 'RETIRED' THEN
    IF TG_OP = 'UPDATE' AND OLD.status = 'PINNED' THEN
      RAISE EXCEPTION 'pinned checkpoint cannot be retired' USING ERRCODE = '23514';
    END IF;
    SELECT p.keep_automatic,p.policy_id INTO keep_count,current_policy
    FROM sim.campaign_checkpoint_retention p
    WHERE (p.world_id,p.branch_id) = (NEW.world_id,NEW.branch_id)
    ORDER BY p.revision DESC LIMIT 1;
    IF keep_count IS NULL OR NEW.policy_id IS DISTINCT FROM current_policy THEN
      RAISE EXCEPTION 'retirement requires the active retention policy'
        USING ERRCODE = '23514';
    END IF;
    WITH completed AS (
      SELECT c.checkpoint_id,c.created_at,h.through_event_seq,s.status
      FROM sim.campaign_checkpoints c
      JOIN sim.campaign_checkpoint_dispatches d USING (world_id,branch_id,request_id)
      JOIN sim.campaign_checkpoint_holds h USING (world_id,branch_id,request_id)
      LEFT JOIN sim.campaign_checkpoint_retention_state s USING (world_id,branch_id,checkpoint_id)
      WHERE (c.world_id,c.branch_id)=(NEW.world_id,NEW.branch_id) AND h.released_at IS NOT NULL
    )
    SELECT count(*) INTO newer_count FROM completed candidate CROSS JOIN completed newer
    WHERE candidate.checkpoint_id = NEW.checkpoint_id AND newer.status IS DISTINCT FROM 'RETIRED'
      AND (newer.through_event_seq,newer.created_at,newer.checkpoint_id)
        > (candidate.through_event_seq,candidate.created_at,candidate.checkpoint_id);
    IF newer_count < keep_count THEN
      RAISE EXCEPTION 'retirement must preserve the newest completed scheduled archives'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.guard_checkpoint_retirement() FROM PUBLIC;
CREATE TRIGGER checkpoint_retirement_scope
  BEFORE INSERT OR UPDATE ON sim.campaign_checkpoint_retention_state
  FOR EACH ROW EXECUTE FUNCTION sim.guard_checkpoint_retirement();

REVOKE ALL ON sim.campaign_checkpoint_retention, sim.campaign_checkpoint_retention_state
  FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT ON sim.campaign_checkpoint_retention, sim.campaign_checkpoint_retention_state
  TO tabletop_app;
GRANT UPDATE (actor_id, status, policy_id, changed_at)
  ON sim.campaign_checkpoint_retention_state TO tabletop_app;
