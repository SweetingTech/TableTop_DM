CREATE FUNCTION sim.require_committed_planned_correction() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,sim AS $$
DECLARE planned jsonb;
BEGIN
  SELECT p.provenance->'planned_correction' INTO planned
  FROM sim.campaign_revision_plans p
  WHERE (p.world_id,p.branch_id,p.request_id)=(NEW.world_id,NEW.source_branch_id,NEW.request_id);
  IF planned IS NULL OR planned='null'::jsonb THEN
    RETURN NEW;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM sim.command_log command
    JOIN sim.events event
      ON (event.world_id,event.branch_id,event.run_id,event.actor_id,event.idempotency_key,event.event_type)=
         (command.world_id,command.branch_id,command.run_id,command.actor_id,command.idempotency_key,
          command.command_type)
    JOIN sim.branch_projections current
      ON (current.world_id,current.branch_id)=(command.world_id,command.branch_id)
    WHERE (command.world_id,command.branch_id,command.run_id,command.actor_id)=
      (NEW.world_id,NEW.branch_id,NEW.run_id,NEW.actor_id)
      AND command.command_type='tabletop.timeline.correct' AND command.input_origin='OPERATOR'
      AND command.idempotency_key='campaign-revision-correction:' || NEW.request_id::text
      AND command.parameters=planned->'request'
      AND command.resulting_state_hash=planned->>'resulting_state_hash'
      AND current.state_hash=command.resulting_state_hash
  ) THEN
    RAISE EXCEPTION 'planned correction was not committed with the campaign revision'
      USING ERRCODE='23514',CONSTRAINT='campaign_activation_requires_planned_correction';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.require_committed_planned_correction() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER complete_planned_campaign_correction
  AFTER INSERT ON sim.campaign_revision_commits DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sim.require_committed_planned_correction();
