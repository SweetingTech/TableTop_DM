-- Retention can run after the API has built narration from a formerly active branch.
-- Serialize it with the same branch lock used for other asynchronous campaign writes.
CREATE OR REPLACE FUNCTION sim.reject_abandoned_campaign_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim AS $$
DECLARE branch sim.branches;
BEGIN
  SELECT * INTO branch FROM sim.branches b WHERE (b.world_id,b.id)=(NEW.world_id,NEW.branch_id)
    FOR SHARE;
  IF branch.branch_kind='CANONICAL' AND branch.status <> 'ACTIVE' THEN
    RAISE EXCEPTION 'canonical continuation was superseded'
      USING ERRCODE='23514',CONSTRAINT='campaign_branch_archived';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER reject_abandoned_campaign_write BEFORE INSERT ON cognition.narration_entries
  FOR EACH ROW EXECUTE FUNCTION sim.reject_abandoned_campaign_write();

-- Recheck continuation visibility in the transaction that reads an existing entry.
CREATE POLICY narration_entries_current_continuation ON cognition.narration_entries
  AS RESTRICTIVE FOR SELECT USING (
    sim.has_world_capability(world_id, 'world.read.all')
    OR EXISTS (
      SELECT 1 FROM sim.branches branch
      WHERE (branch.world_id,branch.id)=(narration_entries.world_id,narration_entries.branch_id)
        AND (branch.branch_kind='TRIAL' OR branch.status='ACTIVE')
    )
  );
