CREATE FUNCTION sim.require_restored_mechanics_hash() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM sim.campaign_revision_plans plan
    WHERE (plan.world_id,plan.branch_id,plan.request_id)=
      (NEW.world_id,NEW.source_branch_id,NEW.request_id)
      AND plan.provenance->>'restore_version'='campaign-restore-1.2.0'
      AND plan.candidate_state_hash IS DISTINCT FROM NEW.state_hash
  ) THEN
    RAISE EXCEPTION 'campaign revision candidate changed' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.require_restored_mechanics_hash() FROM PUBLIC;
CREATE TRIGGER require_restored_mechanics_hash BEFORE INSERT ON sim.campaign_revision_commits
  FOR EACH ROW EXECUTE FUNCTION sim.require_restored_mechanics_hash();
