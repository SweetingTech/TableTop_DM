-- One operator rule per branch. Previous versions remain as trigger provenance.
CREATE TABLE sim.campaign_checkpoint_rules (
  rule_id uuid PRIMARY KEY,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  operator_actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  label text NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 120),
  interval_seconds integer CHECK (interval_seconds BETWEEN 1 AND 2592000),
  event_types text[] NOT NULL DEFAULT '{}',
  anchor_seconds bigint NOT NULL CHECK (anchor_seconds >= 0),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (world_id, branch_id, rule_id),
  FOREIGN KEY (world_id, branch_id) REFERENCES sim.branches(world_id,id) ON DELETE RESTRICT,
  CHECK (cardinality(event_types) <= 32),
  CHECK (interval_seconds IS NOT NULL OR cardinality(event_types) > 0)
);
CREATE UNIQUE INDEX campaign_checkpoint_active_rule
  ON sim.campaign_checkpoint_rules(world_id,branch_id) WHERE active;

CREATE TABLE sim.campaign_checkpoint_dispatches (
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  rule_id uuid NOT NULL,
  request_id uuid NOT NULL,
  source_event_id uuid NOT NULL,
  source_actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  simulated_seconds bigint CHECK (simulated_seconds >= 0),
  cause text NOT NULL CHECK (cause IN ('EVENT','CLOCK')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (world_id,branch_id,request_id),
  UNIQUE (rule_id,source_event_id),
  FOREIGN KEY (world_id,branch_id,rule_id)
    REFERENCES sim.campaign_checkpoint_rules(world_id,branch_id,rule_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,source_event_id)
    REFERENCES sim.events(world_id,branch_id,event_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,request_id)
    REFERENCES sim.campaign_checkpoint_holds(world_id,branch_id,request_id) ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED,
  CHECK (cause <> 'CLOCK' OR simulated_seconds IS NOT NULL)
);
CREATE TRIGGER campaign_checkpoint_dispatches_append_only
  BEFORE UPDATE OR DELETE ON sim.campaign_checkpoint_dispatches
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE FUNCTION sim.checkpoint_rule_storage_owner() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, sim AS $$
  SELECT current_user = pg_get_userbyid(relowner) FROM pg_class
    WHERE oid='sim.campaign_checkpoint_rules'::regclass
$$;
REVOKE ALL ON FUNCTION sim.checkpoint_rule_storage_owner() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.checkpoint_rule_storage_owner() TO tabletop_app;

ALTER TABLE sim.campaign_checkpoint_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_checkpoint_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY checkpoint_rules_read ON sim.campaign_checkpoint_rules FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id) OR sim.checkpoint_rule_storage_owner());
CREATE POLICY checkpoint_rules_insert ON sim.campaign_checkpoint_rules FOR INSERT
  WITH CHECK (
    operator_actor_id=sim.current_actor_id() AND active AND sim.can_read_campaign_checkpoint(world_id)
    AND EXISTS (
      SELECT 1 FROM sim.branches b
      WHERE (b.world_id,b.id)=(campaign_checkpoint_rules.world_id,campaign_checkpoint_rules.branch_id)
        AND b.branch_kind='CANONICAL' AND b.status='ACTIVE'
    )
  );
CREATE POLICY checkpoint_rules_retire ON sim.campaign_checkpoint_rules FOR UPDATE
  USING (active AND sim.can_read_campaign_checkpoint(world_id))
  WITH CHECK (NOT active AND sim.can_read_campaign_checkpoint(world_id));
REVOKE ALL ON sim.campaign_checkpoint_rules FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT, UPDATE (active) ON sim.campaign_checkpoint_rules TO tabletop_app;

ALTER TABLE sim.campaign_checkpoint_dispatches ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_checkpoint_dispatches FORCE ROW LEVEL SECURITY;
CREATE POLICY checkpoint_dispatches_read ON sim.campaign_checkpoint_dispatches FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id) OR sim.checkpoint_rule_storage_owner());
CREATE POLICY checkpoint_dispatches_insert ON sim.campaign_checkpoint_dispatches FOR INSERT
  WITH CHECK (
    sim.checkpoint_rule_storage_owner() AND source_actor_id=sim.current_actor_id()
    AND sim.has_world_capability(world_id,'action.commit')
  );
REVOKE ALL ON sim.campaign_checkpoint_dispatches FROM PUBLIC, tabletop_app;
GRANT SELECT ON sim.campaign_checkpoint_dispatches TO tabletop_app;

-- The trigger owner can inspect the full prefix of the authorized event's branch.
-- These paths preserve FORCE RLS when the migration owner is not a superuser.
CREATE POLICY checkpoint_trigger_events_read ON sim.events FOR SELECT
  USING (sim.checkpoint_rule_storage_owner() AND sim.has_world_capability(world_id,'action.commit'));
CREATE POLICY checkpoint_trigger_commands_read ON sim.command_log FOR SELECT
  USING (sim.checkpoint_rule_storage_owner() AND sim.has_world_capability(world_id,'action.commit'));
CREATE POLICY checkpoint_trigger_projection_read ON sim.branch_projections FOR SELECT
  USING (sim.checkpoint_rule_storage_owner() AND sim.has_world_capability(world_id,'action.commit'));

CREATE POLICY checkpoint_hold_scheduled ON sim.campaign_checkpoint_holds FOR INSERT WITH CHECK (
  sim.checkpoint_rule_storage_owner() AND actor_id=sim.current_actor_id() AND released_at IS NULL
  AND EXISTS (
    SELECT 1 FROM sim.campaign_checkpoint_dispatches job
    WHERE (job.world_id,job.branch_id,job.request_id)=
          (campaign_checkpoint_holds.world_id,campaign_checkpoint_holds.branch_id,
           campaign_checkpoint_holds.request_id)
      AND job.source_actor_id=campaign_checkpoint_holds.actor_id
  )
);

CREATE FUNCTION sim.arm_campaign_checkpoint() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, sim AS $$
DECLARE
  origin sim.events%ROWTYPE;
  rule sim.campaign_checkpoint_rules%ROWTYPE;
  projection sim.branch_projections%ROWTYPE;
  cut sim.events%ROWTYPE;
  seconds bigint;
  prior_seconds bigint;
  ordinal bigint;
  request uuid;
  cause text;
BEGIN
  SELECT * INTO origin FROM sim.events WHERE event_id=NEW.event_id;
  IF NEW.published_at IS NOT NULL OR NOT FOUND OR origin.actor_id IS DISTINCT FROM sim.current_actor_id()
     OR NOT sim.has_world_capability(origin.world_id,'action.commit')
     OR NOT EXISTS (
       SELECT 1 FROM sim.branches b WHERE (b.world_id,b.id)=(origin.world_id,origin.branch_id)
       AND b.branch_kind='CANONICAL' AND b.status='ACTIVE'
     ) THEN
    RETURN NEW;
  END IF;
  SELECT * INTO rule FROM sim.campaign_checkpoint_rules
    WHERE (world_id,branch_id)=(origin.world_id,origin.branch_id) AND active;
  IF NOT FOUND OR (SELECT count(DISTINCT grant_row.capability)
      FROM sim.actors actor JOIN sim.actor_capabilities grant_row ON grant_row.actor_id=actor.id
      WHERE actor.id=rule.operator_actor_id AND actor.is_active AND grant_row.world_id=rule.world_id
        AND grant_row.capability IN ('world.read','world.read.all','run.branch',
                                     'mind.read.all','entity.read.secret')) <> 5 THEN
    RETURN NEW;
  END IF;
  IF EXISTS (
    SELECT 1 FROM sim.campaign_checkpoint_holds
    WHERE (world_id,branch_id)=(origin.world_id,origin.branch_id) AND released_at IS NULL
  ) THEN
    RETURN NEW;
  END IF;
  SELECT * INTO STRICT projection FROM sim.branch_projections
    WHERE (world_id,branch_id)=(origin.world_id,origin.branch_id);
  seconds := (projection.state->'tabletop.clock'->'singleton'->>'seconds')::bigint;
  IF origin.event_type=ANY(rule.event_types) THEN
    cause := 'EVENT';
  ELSIF rule.interval_seconds IS NOT NULL AND seconds IS NOT NULL
        AND origin.event_type LIKE 'tabletop.clock.%' THEN
    SELECT GREATEST(rule.anchor_seconds,max(simulated_seconds)) INTO prior_seconds
      FROM sim.campaign_checkpoint_dispatches WHERE rule_id=rule.rule_id;
    IF seconds < rule.anchor_seconds OR
       (seconds-rule.anchor_seconds)/rule.interval_seconds <=
       (prior_seconds-rule.anchor_seconds)/rule.interval_seconds THEN
      RETURN NEW;
    END IF;
    cause := 'CLOCK';
  ELSE
    RETURN NEW;
  END IF;

  SELECT * INTO STRICT cut FROM sim.events
    WHERE (world_id,branch_id)=(origin.world_id,origin.branch_id) ORDER BY seq_id DESC LIMIT 1;
  SELECT count(*) INTO ordinal FROM sim.command_log
    WHERE (world_id,branch_id)=(origin.world_id,origin.branch_id);
  request := gen_random_uuid();
  INSERT INTO sim.campaign_checkpoint_dispatches
    (world_id,branch_id,rule_id,request_id,source_event_id,source_actor_id,simulated_seconds,cause)
    VALUES (origin.world_id,origin.branch_id,rule.rule_id,request,origin.event_id,origin.actor_id,
            seconds,cause);
  INSERT INTO sim.campaign_checkpoint_holds
    (world_id,branch_id,request_id,actor_id,projection_version,state_hash,command_ordinal,
     through_event_seq,through_event_id,simulated_seconds)
    VALUES (origin.world_id,origin.branch_id,request,origin.actor_id,projection.version,
            projection.state_hash,ordinal,cut.seq_id,cut.event_id,seconds);
  RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION sim.arm_campaign_checkpoint() FROM PUBLIC, tabletop_app;
CREATE CONSTRAINT TRIGGER checkpoint_after_committed_outbox
  AFTER INSERT ON sim.outbox DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
  EXECUTE FUNCTION sim.arm_campaign_checkpoint();
