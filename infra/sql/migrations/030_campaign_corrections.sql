CREATE FUNCTION sim.require_paused_campaign_correction() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,sim AS $$
BEGIN
  IF NEW.input_origin IS DISTINCT FROM 'OPERATOR' OR NEW.embodied_entity_id IS NOT NULL
    OR NOT sim.has_world_capability(NEW.world_id,'action.propose')
    OR NOT sim.has_world_capability(NEW.world_id,'action.commit')
    OR NOT sim.has_world_capability(NEW.world_id,'world.read.all')
    OR NOT sim.has_world_capability(NEW.world_id,'entity.control')
    OR NOT sim.has_world_capability(NEW.world_id,'run.branch') THEN
    RAISE EXCEPTION 'campaign correction requires current operator authority' USING ERRCODE='42501';
  END IF;

  PERFORM 1 FROM sim.campaign_continuations active
  JOIN sim.campaign_revision_commits revision
    ON (revision.world_id,revision.branch_id,revision.epoch)=(active.world_id,active.branch_id,active.epoch)
  JOIN sim.runs live
    ON (live.world_id,live.branch_id,live.id)=(revision.world_id,revision.branch_id,revision.run_id)
  WHERE (active.world_id,active.branch_id,live.id)=(NEW.world_id,NEW.branch_id,NEW.run_id)
    AND NEW.parameters->'expected_epoch'=to_jsonb(active.epoch)
    AND revision.committed_at IS NOT NULL AND live.run_kind='LIVE' AND live.status='PAUSED'
  FOR SHARE OF active,live;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'campaign correction requires the paused active revision'
      USING ERRCODE='23514',CONSTRAINT='campaign_correction_requires_paused_revision';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.require_paused_campaign_correction() FROM PUBLIC;
CREATE TRIGGER require_paused_campaign_correction BEFORE INSERT ON sim.command_log
  FOR EACH ROW WHEN (NEW.command_type='tabletop.timeline.correct')
  EXECUTE FUNCTION sim.require_paused_campaign_correction();
