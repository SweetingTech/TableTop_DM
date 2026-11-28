CREATE TABLE sim.campaign_revision_resumes (
  world_id uuid NOT NULL,
  source_branch_id uuid NOT NULL,
  revision_request_id uuid NOT NULL,
  request_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK (epoch > 0),
  run_clock boolean NOT NULL,
  clock_event_id uuid,
  human_controllers integer NOT NULL CHECK (human_controllers >= 0),
  autonomous_controllers integer NOT NULL CHECK (autonomous_controllers >= 0),
  paused_controllers integer NOT NULL CHECK (paused_controllers >= 0),
  resumed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (world_id,source_branch_id,revision_request_id),
  UNIQUE (world_id,request_id),
  FOREIGN KEY (world_id,source_branch_id,revision_request_id)
    REFERENCES sim.campaign_revision_commits(world_id,source_branch_id,request_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,epoch)
    REFERENCES sim.campaign_timeline_lineage(world_id,branch_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,run_id)
    REFERENCES sim.runs(world_id,branch_id,id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,run_id,clock_event_id)
    REFERENCES sim.events(world_id,branch_id,run_id,event_id) ON DELETE RESTRICT,
  CHECK (run_clock OR clock_event_id IS NULL)
);
CREATE TRIGGER campaign_revision_resumes_immutable
  BEFORE UPDATE OR DELETE ON sim.campaign_revision_resumes
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
ALTER TABLE sim.campaign_revision_resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_revision_resumes FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_revision_resume_read ON sim.campaign_revision_resumes FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id));
CREATE POLICY campaign_revision_resume_create ON sim.campaign_revision_resumes FOR INSERT
  WITH CHECK (
    actor_id=sim.current_actor_id() AND sim.can_read_campaign_checkpoint(world_id)
    AND sim.can_mutate_branch(world_id,branch_id)
    AND sim.has_world_capability(world_id,'entity.control')
    AND sim.has_world_capability(world_id,'mind.write.all')
    AND EXISTS (
      SELECT 1 FROM sim.campaign_revision_commits c
      JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(c.world_id,c.branch_id,c.run_id)
      WHERE (c.world_id,c.source_branch_id,c.request_id) =
        (campaign_revision_resumes.world_id,campaign_revision_resumes.source_branch_id,
         campaign_revision_resumes.revision_request_id)
      AND (c.branch_id,c.run_id,c.epoch) =
        (campaign_revision_resumes.branch_id,campaign_revision_resumes.run_id,campaign_revision_resumes.epoch)
      AND c.committed_at IS NOT NULL AND r.status='RUNNING' AND r.run_kind='LIVE'
    )
  );
REVOKE ALL ON sim.campaign_revision_resumes FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT ON sim.campaign_revision_resumes TO tabletop_app;

CREATE FUNCTION sim.require_resumed_campaign_command() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,sim AS $$
BEGIN
  IF NEW.input_origin <> 'OPERATOR' AND EXISTS (
    SELECT 1 FROM sim.campaign_revision_commits c
    JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(c.world_id,c.branch_id,c.run_id)
    WHERE (c.world_id,c.branch_id,c.run_id)=(NEW.world_id,NEW.branch_id,NEW.run_id)
      AND c.committed_at IS NOT NULL AND r.status='PAUSED'
  ) THEN
    RAISE EXCEPTION 'the restored campaign is paused'
      USING ERRCODE='23514',CONSTRAINT='campaign_revision_paused';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.require_resumed_campaign_command() FROM PUBLIC;
CREATE TRIGGER require_resumed_campaign_command BEFORE INSERT ON sim.command_log
  FOR EACH ROW EXECUTE FUNCTION sim.require_resumed_campaign_command();

-- Runtime repositories and asynchronous model callbacks also write outside the command ledger.
CREATE FUNCTION sim.reject_abandoned_campaign_write() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim AS $$
DECLARE branch sim.branches;
BEGIN
  SELECT * INTO branch FROM sim.branches b WHERE (b.world_id,b.id)=(NEW.world_id,NEW.branch_id)
    FOR SHARE;
  IF branch.branch_kind='CANONICAL' AND branch.status <> 'ACTIVE' THEN
    RAISE EXCEPTION 'canonical continuation was superseded' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.reject_abandoned_campaign_write() FROM PUBLIC;
DO $$
DECLARE name regclass;
BEGIN
  FOREACH name IN ARRAY ARRAY[
    'sim.schedules'::regclass,
    'cognition.mind_states'::regclass,
    'cognition.observations'::regclass,
    'cognition.beliefs'::regclass,
    'cognition.belief_evidence'::regclass,
    'cognition.memories'::regclass,
    'cognition.relationships'::regclass,
    'cognition.relationship_changes'::regclass,
    'cognition.runtime_assignments'::regclass,
    'cognition.controller_assignments'::regclass,
    'cognition.controller_handoffs'::regclass,
    'cognition.decision_traces'::regclass,
    'cognition.character_proposal_receipts'::regclass,
    'population.materialized_people'::regclass,
    'population.lifecycle_transitions'::regclass
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER reject_abandoned_campaign_write BEFORE INSERT OR UPDATE ON %s '
      'FOR EACH ROW EXECUTE FUNCTION sim.reject_abandoned_campaign_write()',name);
  END LOOP;
END;
$$;
