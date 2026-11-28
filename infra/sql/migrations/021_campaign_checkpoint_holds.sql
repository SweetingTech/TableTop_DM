-- A hold freezes one branch's action boundary while its ordered outbox drains.
CREATE TABLE sim.campaign_checkpoint_holds (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  request_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  projection_version bigint NOT NULL CHECK (projection_version >= 0),
  state_hash text NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
  command_ordinal bigint NOT NULL CHECK (command_ordinal >= 0),
  through_event_seq bigint NOT NULL CHECK (through_event_seq >= 0),
  through_event_id uuid,
  simulated_seconds bigint CHECK (simulated_seconds >= 0),
  held_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  released_at timestamptz CHECK (released_at >= held_at),
  PRIMARY KEY (world_id, branch_id, request_id),
  FOREIGN KEY (world_id, branch_id) REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, through_event_id)
    REFERENCES sim.events(world_id, branch_id, event_id) ON DELETE RESTRICT,
  CHECK ((through_event_seq = 0) = (through_event_id IS NULL)),
  CHECK (command_ordinal = 0 OR through_event_seq > 0)
);

CREATE UNIQUE INDEX campaign_checkpoint_hold_active
  ON sim.campaign_checkpoint_holds(world_id, branch_id) WHERE released_at IS NULL;

ALTER TABLE sim.campaign_checkpoint_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_checkpoint_holds FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_checkpoint_hold_read ON sim.campaign_checkpoint_holds FOR SELECT
  USING (
    sim.has_world_capability(world_id, 'world.read')
    OR sim.has_world_capability(world_id, 'action.commit')
    OR sim.has_world_capability(world_id, 'run.branch')
  );
CREATE POLICY campaign_checkpoint_hold_create ON sim.campaign_checkpoint_holds FOR INSERT
  WITH CHECK (
    actor_id = (SELECT sim.current_actor_id()) AND released_at IS NULL
    AND sim.has_world_capability(world_id, 'run.branch')
    AND sim.has_world_capability(world_id, 'world.read.all')
    AND sim.has_world_capability(world_id, 'mind.read.all')
    AND EXISTS (
      SELECT 1 FROM sim.branches branch
      WHERE (branch.world_id, branch.id) =
        (campaign_checkpoint_holds.world_id, campaign_checkpoint_holds.branch_id)
        AND branch.branch_kind = 'CANONICAL' AND branch.status = 'ACTIVE'
    )
  );
CREATE POLICY campaign_checkpoint_hold_release ON sim.campaign_checkpoint_holds FOR UPDATE
  USING (
    released_at IS NULL
    AND sim.has_world_capability(world_id, 'run.branch')
    AND sim.has_world_capability(world_id, 'world.read.all')
    AND sim.has_world_capability(world_id, 'mind.read.all')
  )
  WITH CHECK (
    released_at IS NOT NULL
    AND sim.has_world_capability(world_id, 'run.branch')
    AND sim.has_world_capability(world_id, 'world.read.all')
    AND sim.has_world_capability(world_id, 'mind.read.all')
  );
REVOKE ALL ON sim.campaign_checkpoint_holds FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT, UPDATE (released_at) ON sim.campaign_checkpoint_holds TO tabletop_app;
