-- Complete checkpoints retain private state outside projection-only trial snapshots.
CREATE FUNCTION sim.can_read_campaign_checkpoint(target_world uuid) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, sim AS $$
  SELECT sim.has_world_capability(target_world, 'world.read')
    AND sim.has_world_capability(target_world, 'run.branch')
    AND sim.has_world_capability(target_world, 'world.read.all')
    AND sim.has_world_capability(target_world, 'mind.read.all')
    AND sim.has_world_capability(target_world, 'entity.read.secret')
$$;
REVOKE ALL ON FUNCTION sim.can_read_campaign_checkpoint(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.can_read_campaign_checkpoint(uuid) TO tabletop_app;

CREATE TABLE sim.campaign_checkpoints (
  checkpoint_id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  request_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  label text NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 160),
  manifest jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (world_id, branch_id, request_id),
  FOREIGN KEY (world_id, branch_id, request_id)
    REFERENCES sim.campaign_checkpoint_holds(world_id, branch_id, request_id) ON DELETE RESTRICT,
  CHECK ((manifest->>'format' = 'tabletop.campaign-checkpoint/v1') IS TRUE),
  CHECK ((manifest->>'checkpoint_id' = checkpoint_id::text) IS TRUE),
  CHECK ((manifest->'boundary'->>'world_id' = world_id::text) IS TRUE),
  CHECK ((manifest->'boundary'->>'branch_id' = branch_id::text) IS TRUE),
  CHECK ((manifest->'boundary'->>'capture_request_id' = request_id::text) IS TRUE),
  CHECK ((manifest->>'artifact_hash' ~ '^[0-9a-f]{64}$') IS TRUE)
);

CREATE INDEX campaign_checkpoint_branch_history
  ON sim.campaign_checkpoints(world_id, branch_id, created_at DESC, checkpoint_id);
CREATE TRIGGER campaign_checkpoints_append_only BEFORE UPDATE OR DELETE ON sim.campaign_checkpoints
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

ALTER TABLE sim.campaign_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_checkpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_checkpoints_read ON sim.campaign_checkpoints FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id));
CREATE POLICY campaign_checkpoints_create ON sim.campaign_checkpoints FOR INSERT WITH CHECK (
  actor_id = (SELECT sim.current_actor_id())
  AND sim.can_read_campaign_checkpoint(world_id)
  AND EXISTS (
    SELECT 1 FROM sim.campaign_checkpoint_holds hold
    WHERE (hold.world_id, hold.branch_id, hold.request_id) =
          (campaign_checkpoints.world_id, campaign_checkpoints.branch_id, campaign_checkpoints.request_id)
      AND hold.released_at IS NULL
      AND manifest->'boundary'->>'projection_version' = hold.projection_version::text
      AND manifest->'boundary'->>'state_hash' = hold.state_hash
      AND manifest->'boundary'->>'command_ordinal' = hold.command_ordinal::text
      AND manifest->'boundary'->>'through_event_seq' = hold.through_event_seq::text
      AND (manifest->'boundary'->>'through_event_id') IS NOT DISTINCT FROM hold.through_event_id::text
      AND (manifest->'boundary'->>'simulated_seconds') IS NOT DISTINCT FROM hold.simulated_seconds::text
      AND NOT EXISTS (
        SELECT 1 FROM sim.outbox work JOIN sim.events source ON source.event_id = work.event_id
        WHERE (source.world_id, source.branch_id) = (hold.world_id, hold.branch_id)
          AND source.seq_id <= hold.through_event_seq AND work.published_at IS NULL
      )
  )
);
REVOKE ALL ON sim.campaign_checkpoints FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT ON sim.campaign_checkpoints TO tabletop_app;

CREATE POLICY checkpoint_world_due_work_read ON sim.world_due_work FOR SELECT USING (
  sim.can_read_campaign_checkpoint(world_id)
  AND EXISTS (
    SELECT 1 FROM sim.campaign_checkpoint_holds hold
    WHERE (hold.world_id,hold.branch_id) = (world_due_work.world_id,world_due_work.branch_id)
      AND hold.released_at IS NULL
  )
);

-- Checkpoint collection can fingerprint pinned authored revisions without
-- granting the operator access to unrelated private cards or future revisions.
CREATE POLICY card_revisions_checkpoint_pin ON tabletop.character_card_revisions FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM tabletop.character_bindings binding
    JOIN sim.campaign_checkpoint_holds hold
      ON (hold.world_id,hold.branch_id) = (binding.world_id,binding.branch_id)
    WHERE (binding.character_id,binding.card_revision_id) =
      (character_card_revisions.character_id,character_card_revisions.revision_id)
      AND hold.released_at IS NULL
      AND sim.can_read_campaign_checkpoint(binding.world_id)
  )
);
