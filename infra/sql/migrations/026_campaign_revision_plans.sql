CREATE TABLE sim.campaign_revision_plans (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  request_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  expected_epoch bigint NOT NULL CHECK (expected_epoch BETWEEN 0 AND 9223372036854775806),
  source_checkpoint_id uuid NOT NULL,
  source_archive_hash text NOT NULL CHECK (source_archive_hash ~ '^[0-9a-f]{64}$'),
  reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 1000),
  seed_policy text NOT NULL CHECK (seed_policy IN ('REUSE_CHECKPOINT_SEED', 'FRESH_SEED')),
  seed bigint NOT NULL,
  source_live_run_id uuid NOT NULL,
  successor_branch_id uuid NOT NULL UNIQUE,
  successor_run_id uuid NOT NULL UNIQUE,
  candidate_state_hash text NOT NULL CHECK (candidate_state_hash ~ '^[0-9a-f]{64}$'),
  provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  cancelled_at timestamptz CHECK (cancelled_at >= created_at),
  PRIMARY KEY (world_id, branch_id, request_id),
  FOREIGN KEY (world_id, branch_id, expected_epoch)
    REFERENCES sim.campaign_timeline_lineage(world_id, branch_id, epoch) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, source_checkpoint_id)
    REFERENCES sim.campaign_checkpoints(world_id, branch_id, checkpoint_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, source_live_run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  CHECK (branch_id <> successor_branch_id AND source_live_run_id <> successor_run_id)
);
CREATE INDEX campaign_revision_plan_live_checkpoint
  ON sim.campaign_revision_plans (world_id, branch_id, source_checkpoint_id)
  WHERE cancelled_at IS NULL;

ALTER TABLE sim.campaign_revision_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_revision_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_revision_plan_read ON sim.campaign_revision_plans FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id));
CREATE POLICY campaign_revision_plan_prepare ON sim.campaign_revision_plans FOR INSERT
  WITH CHECK (
    actor_id=(SELECT sim.current_actor_id()) AND cancelled_at IS NULL
    AND sim.can_read_campaign_checkpoint(world_id) AND sim.has_world_capability(world_id,'action.commit')
  );
CREATE POLICY campaign_revision_plan_cancel ON sim.campaign_revision_plans FOR UPDATE
  USING (
    cancelled_at IS NULL AND actor_id=(SELECT sim.current_actor_id())
    AND sim.can_read_campaign_checkpoint(world_id) AND sim.has_world_capability(world_id,'action.commit')
  )
  WITH CHECK (
    cancelled_at IS NOT NULL AND actor_id=(SELECT sim.current_actor_id())
    AND sim.can_read_campaign_checkpoint(world_id) AND sim.has_world_capability(world_id,'action.commit')
  );
REVOKE ALL ON sim.campaign_revision_plans FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT,UPDATE (cancelled_at) ON sim.campaign_revision_plans TO tabletop_app;

CREATE FUNCTION sim.guard_campaign_revision_plan() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, sim AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(
    format('tabletop:checkpoint-archives:%s:%s',NEW.world_id,NEW.branch_id),0));
  IF NOT EXISTS (
    SELECT 1 FROM sim.campaign_continuations head
    JOIN sim.branches b ON (b.world_id,b.id)=(head.world_id,head.branch_id)
    JOIN sim.campaign_checkpoints c ON (c.world_id,c.branch_id)=(head.world_id,head.branch_id)
    WHERE (head.world_id,head.branch_id,head.epoch)=(NEW.world_id,NEW.branch_id,NEW.expected_epoch)
      AND b.branch_kind='CANONICAL' AND b.status='ACTIVE'
      AND c.checkpoint_id=NEW.source_checkpoint_id
      AND c.manifest->>'artifact_hash'=NEW.source_archive_hash
      AND c.manifest->'boundary'->>'continuation_epoch'=NEW.expected_epoch::text
  ) OR EXISTS (
    SELECT 1 FROM sim.campaign_checkpoint_retention_state state
    WHERE (state.world_id,state.branch_id,state.checkpoint_id)=
      (NEW.world_id,NEW.branch_id,NEW.source_checkpoint_id)
      AND state.status='RETIRED'
  ) THEN
    RAISE EXCEPTION 'revision plan requires an available checkpoint on the active continuation'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.guard_campaign_revision_plan() FROM PUBLIC;
CREATE TRIGGER guard_campaign_revision_plan
  BEFORE INSERT ON sim.campaign_revision_plans
  FOR EACH ROW EXECUTE FUNCTION sim.guard_campaign_revision_plan();

CREATE FUNCTION sim.guard_revision_checkpoint_retention() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, sim AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(
    format('tabletop:checkpoint-archives:%s:%s',NEW.world_id,NEW.branch_id),0));
  IF EXISTS (
    SELECT 1 FROM sim.campaign_revision_plans plan
    WHERE (plan.world_id,plan.branch_id,plan.source_checkpoint_id)=
      (NEW.world_id,NEW.branch_id,NEW.checkpoint_id) AND plan.cancelled_at IS NULL
  ) THEN
    RAISE EXCEPTION 'checkpoint is protected by a prepared revision' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.guard_revision_checkpoint_retention() FROM PUBLIC;
CREATE TRIGGER guard_revision_checkpoint_retention
  BEFORE INSERT OR UPDATE ON sim.campaign_checkpoint_retention_state
  FOR EACH ROW WHEN (NEW.status='RETIRED') EXECUTE FUNCTION sim.guard_revision_checkpoint_retention();
