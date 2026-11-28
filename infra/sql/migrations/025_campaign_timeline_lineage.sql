-- Historical canonical branches can coexist once a typed continuation switches the head.
DROP INDEX sim.uq_sim_one_canonical_branch;
CREATE UNIQUE INDEX uq_sim_one_canonical_branch
  ON sim.branches(world_id) WHERE branch_kind='CANONICAL' AND status='ACTIVE';

CREATE TABLE sim.campaign_timeline_lineage (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  epoch bigint NOT NULL CHECK (epoch >= 0),
  parent_branch_id uuid,
  parent_epoch bigint,
  source_checkpoint_id uuid,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (world_id, branch_id),
  UNIQUE (world_id, epoch),
  UNIQUE (world_id, branch_id, epoch),
  FOREIGN KEY (world_id, branch_id) REFERENCES sim.branches(world_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, parent_branch_id, parent_epoch)
    REFERENCES sim.campaign_timeline_lineage(world_id, branch_id, epoch) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, parent_branch_id, source_checkpoint_id)
    REFERENCES sim.campaign_checkpoints(world_id, branch_id, checkpoint_id) ON DELETE RESTRICT,
  CHECK (
    (epoch = 0 AND parent_branch_id IS NULL AND parent_epoch IS NULL AND source_checkpoint_id IS NULL)
    OR (epoch > 0 AND parent_branch_id IS NOT NULL AND parent_epoch = epoch - 1
        AND parent_epoch IS NOT NULL AND source_checkpoint_id IS NOT NULL
        AND branch_id <> parent_branch_id)
  )
);

CREATE TABLE sim.campaign_continuations (
  world_id uuid PRIMARY KEY REFERENCES sim.worlds(id) ON DELETE RESTRICT,
  branch_id uuid NOT NULL,
  epoch bigint NOT NULL,
  FOREIGN KEY (world_id, branch_id, epoch)
    REFERENCES sim.campaign_timeline_lineage(world_id, branch_id, epoch) ON DELETE RESTRICT
);

INSERT INTO sim.campaign_timeline_lineage (world_id, branch_id, epoch, created_at)
SELECT world_id,id,0,created_at FROM sim.branches WHERE branch_kind='CANONICAL';
INSERT INTO sim.campaign_continuations (world_id, branch_id, epoch)
SELECT world_id,branch_id,epoch FROM sim.campaign_timeline_lineage;

CREATE TRIGGER campaign_timeline_append_only
  BEFORE UPDATE OR DELETE ON sim.campaign_timeline_lineage
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE FUNCTION sim.campaign_timeline_storage_owner() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, sim AS $$
  SELECT current_user = pg_get_userbyid(relowner) FROM pg_class
  WHERE oid='sim.campaign_continuations'::regclass
$$;
REVOKE ALL ON FUNCTION sim.campaign_timeline_storage_owner() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.campaign_timeline_storage_owner() TO tabletop_app;

ALTER TABLE sim.campaign_timeline_lineage ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_timeline_lineage FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_lineage_read ON sim.campaign_timeline_lineage FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id) OR sim.campaign_timeline_storage_owner());
CREATE POLICY campaign_lineage_bootstrap ON sim.campaign_timeline_lineage FOR INSERT
  WITH CHECK (sim.campaign_timeline_storage_owner() AND epoch=0);

ALTER TABLE sim.campaign_continuations ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_continuations FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_continuation_read ON sim.campaign_continuations FOR SELECT
  USING (sim.has_world_capability(world_id,'world.read') OR sim.campaign_timeline_storage_owner());
CREATE POLICY campaign_continuation_bootstrap ON sim.campaign_continuations FOR INSERT
  WITH CHECK (sim.campaign_timeline_storage_owner() AND epoch=0);

REVOKE ALL ON sim.campaign_timeline_lineage,sim.campaign_continuations FROM PUBLIC,tabletop_app;
GRANT SELECT ON sim.campaign_timeline_lineage,sim.campaign_continuations TO tabletop_app;

CREATE POLICY campaign_checkpoint_continuation ON sim.campaign_checkpoints
  AS RESTRICTIVE FOR INSERT WITH CHECK (
    EXISTS (
      SELECT 1 FROM sim.campaign_continuations c
      WHERE (c.world_id,c.branch_id)=(campaign_checkpoints.world_id,campaign_checkpoints.branch_id)
        AND manifest->'boundary'->>'continuation_epoch'=c.epoch::text
    )
  );

CREATE FUNCTION sim.bootstrap_campaign_continuation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, sim AS $$
BEGIN
  IF NEW.branch_kind = 'CANONICAL' THEN
    INSERT INTO sim.campaign_timeline_lineage (world_id,branch_id,epoch,created_at)
    VALUES (NEW.world_id,NEW.id,0,NEW.created_at);
    INSERT INTO sim.campaign_continuations (world_id,branch_id,epoch)
    VALUES (NEW.world_id,NEW.id,0);
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.bootstrap_campaign_continuation() FROM PUBLIC;
CREATE TRIGGER branch_campaign_continuation
  AFTER INSERT ON sim.branches FOR EACH ROW EXECUTE FUNCTION sim.bootstrap_campaign_continuation();

CREATE OR REPLACE FUNCTION sim.can_mutate_branch(target_world_id uuid, target_branch_id uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, sim AS $$
  SELECT EXISTS (
    SELECT 1 FROM sim.branches b
    WHERE (b.world_id,b.id)=(target_world_id,target_branch_id) AND b.status='ACTIVE'
      AND (
        (b.branch_kind='CANONICAL' AND sim.has_world_capability(target_world_id,'action.commit')
          AND EXISTS (
            SELECT 1 FROM sim.campaign_continuations c
            WHERE (c.world_id,c.branch_id)=(target_world_id,target_branch_id)
          ))
        OR (b.branch_kind='TRIAL' AND sim.has_world_capability(target_world_id,'action.propose'))
      )
  )
$$;
