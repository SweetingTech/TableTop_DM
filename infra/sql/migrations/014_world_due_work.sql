-- One outstanding clock step per canonical branch. Completed steps are in the
-- command ledger. The operational lease and backoff never enter replay state.
CREATE TABLE sim.world_due_work (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  executor_actor_id uuid NOT NULL REFERENCES sim.actors(id),
  epoch bigint NOT NULL CHECK (epoch > 0),
  step bigint NOT NULL CHECK (step >= 0),
  due_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL CHECK (available_at >= due_at),
  lease_token uuid,
  lease_until timestamptz,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  PRIMARY KEY (world_id, branch_id),
  FOREIGN KEY (world_id, branch_id, run_id)
    REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  CHECK ((lease_token IS NULL) = (lease_until IS NULL))
);

-- Preserve scheduled progress when updating a running world from schema 013.
INSERT INTO sim.world_due_work
  (world_id, branch_id, run_id, executor_actor_id, epoch, step, due_at, available_at)
SELECT p.world_id, p.branch_id, r.id, (clock->>'executor_actor_id')::uuid,
       (clock->>'epoch')::bigint, (clock->>'step')::bigint,
       (clock->>'next_due')::timestamptz, (clock->>'next_due')::timestamptz
FROM sim.branch_projections p
JOIN sim.branches b ON (b.world_id,b.id)=(p.world_id,p.branch_id)
CROSS JOIN LATERAL (SELECT p.state->'tabletop.clock'->'singleton' AS clock) c
JOIN sim.runs r ON (r.world_id,r.branch_id,r.id) =
  (p.world_id,p.branch_id,(clock->>'run_id')::uuid)
WHERE b.branch_kind='CANONICAL' AND r.run_kind='LIVE' AND clock->>'paused'='false';

ALTER TABLE sim.world_due_work ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.world_due_work FORCE ROW LEVEL SECURITY;
CREATE POLICY world_due_work_access ON sim.world_due_work
  USING (sim.has_world_capability(world_id,'action.commit') AND (
    sim.has_world_capability(world_id,'entity.control')
    OR (executor_actor_id=sim.current_actor_id()
        AND sim.has_world_capability(world_id,'world.read')
        AND sim.has_world_capability(world_id,'action.propose'))))
  WITH CHECK (sim.has_world_capability(world_id,'action.commit') AND (
    sim.has_world_capability(world_id,'entity.control')
    OR (executor_actor_id=sim.current_actor_id()
        AND sim.has_world_capability(world_id,'world.read')
        AND sim.has_world_capability(world_id,'action.propose'))));
GRANT SELECT, INSERT, UPDATE, DELETE ON sim.world_due_work TO tabletop_app;

-- A projector can seek the first unfinished event on the same branch topic.
CREATE INDEX idx_sim_outbox_topic_head
  ON sim.outbox(topic,id) WHERE published_at IS NULL;
