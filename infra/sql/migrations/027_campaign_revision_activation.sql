CREATE TABLE sim.campaign_revision_commits (
  world_id uuid NOT NULL,
  source_branch_id uuid NOT NULL,
  request_id uuid NOT NULL,
  actor_id uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  branch_id uuid NOT NULL UNIQUE,
  run_id uuid NOT NULL UNIQUE,
  epoch bigint NOT NULL CHECK (epoch > 0),
  state_hash text NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
  transaction_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
  committed_at timestamptz,
  PRIMARY KEY (world_id,source_branch_id,request_id),
  FOREIGN KEY (world_id,source_branch_id,request_id)
    REFERENCES sim.campaign_revision_plans(world_id,branch_id,request_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,epoch)
    REFERENCES sim.campaign_timeline_lineage(world_id,branch_id,epoch)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (world_id,branch_id,run_id) REFERENCES sim.runs(world_id,branch_id,id)
    DEFERRABLE INITIALLY DEFERRED
);

ALTER TABLE sim.campaign_revision_commits ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_revision_commits FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_revision_commit_read ON sim.campaign_revision_commits FOR SELECT
  USING (sim.can_read_campaign_checkpoint(world_id) OR sim.campaign_timeline_storage_owner());
CREATE POLICY campaign_revision_commit_start ON sim.campaign_revision_commits FOR INSERT
  WITH CHECK (sim.campaign_timeline_storage_owner() AND committed_at IS NULL);
CREATE POLICY campaign_revision_commit_finish ON sim.campaign_revision_commits FOR UPDATE
  USING (sim.campaign_timeline_storage_owner() AND committed_at IS NULL
    AND transaction_id=pg_current_xact_id())
  WITH CHECK (sim.campaign_timeline_storage_owner() AND committed_at IS NOT NULL
    AND transaction_id=pg_current_xact_id());
REVOKE ALL ON sim.campaign_revision_commits FROM PUBLIC,tabletop_app;
GRANT SELECT ON sim.campaign_revision_commits TO tabletop_app;

CREATE FUNCTION sim.guard_committed_revision_cancel() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(
    format('tabletop:checkpoint-archives:%s:%s',NEW.world_id,NEW.branch_id),0));
  IF EXISTS (
    SELECT 1 FROM sim.campaign_revision_commits c
    WHERE (c.world_id,c.source_branch_id,c.request_id)=(NEW.world_id,NEW.branch_id,NEW.request_id)
  ) THEN
    RAISE EXCEPTION 'campaign revision is already committed' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION sim.guard_committed_revision_cancel() FROM PUBLIC;
CREATE TRIGGER guard_committed_revision_cancel BEFORE UPDATE ON sim.campaign_revision_plans
  FOR EACH ROW EXECUTE FUNCTION sim.guard_committed_revision_cancel();

CREATE FUNCTION sim.restoring_campaign_branch(w uuid,b uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog,sim AS $$
  SELECT EXISTS (
    SELECT 1 FROM sim.campaign_revision_commits restore
    WHERE (restore.world_id,restore.branch_id)=(w,b)
      AND restore.actor_id=sim.current_actor_id()
      AND restore.transaction_id=pg_current_xact_id_if_assigned()
      AND restore.committed_at IS NULL
  )
$$;
REVOKE ALL ON FUNCTION sim.restoring_campaign_branch(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.restoring_campaign_branch(uuid,uuid) TO tabletop_app;

CREATE POLICY restored_campaign_lineage ON sim.campaign_timeline_lineage FOR INSERT
  WITH CHECK (sim.campaign_timeline_storage_owner() AND epoch>0
    AND sim.restoring_campaign_branch(world_id,branch_id));
CREATE POLICY restored_campaign_continuation ON sim.campaign_continuations FOR UPDATE
  USING (sim.campaign_timeline_storage_owner())
  WITH CHECK (sim.campaign_timeline_storage_owner() AND epoch>0
    AND sim.restoring_campaign_branch(world_id,branch_id));

CREATE OR REPLACE FUNCTION sim.bootstrap_campaign_continuation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,sim AS $$
BEGIN
  IF NEW.branch_kind='CANONICAL' AND NOT sim.restoring_campaign_branch(NEW.world_id,NEW.id) THEN
    INSERT INTO sim.campaign_timeline_lineage (world_id,branch_id,epoch,created_at)
    VALUES (NEW.world_id,NEW.id,0,NEW.created_at);
    INSERT INTO sim.campaign_continuations (world_id,branch_id,epoch)
    VALUES (NEW.world_id,NEW.id,0);
  END IF;
  RETURN NEW;
END;
$$;

CREATE FUNCTION sim.start_campaign_revision(w uuid,b uuid,request uuid,hold_request uuid,restored_hash text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,sim AS $$
DECLARE
  plan sim.campaign_revision_plans;
  hold sim.campaign_checkpoint_holds;
BEGIN
  IF NOT sim.can_read_campaign_checkpoint(w)
    OR NOT sim.has_world_capability(w,'action.commit')
    OR NOT sim.has_world_capability(w,'entity.control')
    OR NOT sim.has_world_capability(w,'mind.write.all') THEN
    RAISE EXCEPTION 'campaign restore requires current operator authority' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(format('tabletop:checkpoint-archives:%s:%s',w,b),0));
  PERFORM id FROM sim.branches WHERE (world_id,id)=(w,b)
    AND branch_kind='CANONICAL' AND status='ACTIVE' FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'the active continuation changed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO plan FROM sim.campaign_revision_plans p
  WHERE (p.world_id,p.branch_id,p.request_id)=(w,b,request) AND p.cancelled_at IS NULL
    AND p.actor_id=sim.current_actor_id();
  IF NOT FOUND OR NOT EXISTS (
    SELECT 1 FROM sim.campaign_continuations c
    WHERE (c.world_id,c.branch_id,c.epoch)=(w,b,plan.expected_epoch)
  ) THEN
    RAISE EXCEPTION 'campaign revision plan is unavailable or stale' USING ERRCODE='23514';
  END IF;
  IF plan.provenance->>'restore_version'='campaign-restore-1.1.0'
    AND plan.candidate_state_hash IS DISTINCT FROM restored_hash THEN
    RAISE EXCEPTION 'campaign revision candidate changed' USING ERRCODE='23514';
  END IF;
  SELECT * INTO hold FROM sim.campaign_checkpoint_holds h
  WHERE (h.world_id,h.branch_id,h.request_id)=(w,b,hold_request)
    AND h.released_at IS NULL AND h.actor_id=sim.current_actor_id();
  IF NOT FOUND OR NOT EXISTS (
    SELECT 1 FROM sim.branch_projections p WHERE (p.world_id,p.branch_id)=(w,b)
      AND (p.version,p.state_hash)=(hold.projection_version,hold.state_hash)
  ) OR EXISTS (
    SELECT 1 FROM sim.outbox pending JOIN sim.events e ON e.event_id=pending.event_id
    WHERE (e.world_id,e.branch_id)=(w,b) AND pending.published_at IS NULL
  ) THEN
    RAISE EXCEPTION 'campaign revision requires a drained live branch' USING ERRCODE='23514';
  END IF;

  INSERT INTO sim.campaign_revision_commits
    (world_id,source_branch_id,request_id,actor_id,branch_id,run_id,epoch,state_hash)
  VALUES (w,b,request,plan.actor_id,plan.successor_branch_id,plan.successor_run_id,
    plan.expected_epoch+1,restored_hash);
  UPDATE sim.branches SET status='ARCHIVED',completed_at=clock_timestamp() WHERE (world_id,id)=(w,b);
  INSERT INTO sim.branches(id,world_id,branch_kind,name,seed,status)
  VALUES (plan.successor_branch_id,w,'CANONICAL',
    format('Canonical continuation %s',plan.expected_epoch+1),plan.seed,'ACTIVE');
  INSERT INTO sim.campaign_timeline_lineage
    (world_id,branch_id,epoch,parent_branch_id,parent_epoch,source_checkpoint_id)
  VALUES (w,plan.successor_branch_id,plan.expected_epoch+1,b,plan.expected_epoch,plan.source_checkpoint_id);
  UPDATE sim.campaign_continuations SET branch_id=plan.successor_branch_id,epoch=plan.expected_epoch+1
  WHERE (world_id,branch_id,epoch)=(w,b,plan.expected_epoch);
  UPDATE sim.runs SET status='CANCELLED',
    completed_at=CASE WHEN started_at IS NOT NULL THEN clock_timestamp() END
  WHERE (world_id,branch_id)=(w,b) AND status IN ('QUEUED','RUNNING','PAUSED');
  DELETE FROM sim.world_due_work WHERE (world_id,branch_id)=(w,b);
  UPDATE sim.campaign_checkpoint_holds SET released_at=clock_timestamp()
  WHERE (world_id,branch_id,request_id)=(w,b,hold_request);
END;
$$;
REVOKE ALL ON FUNCTION sim.start_campaign_revision(uuid,uuid,uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.start_campaign_revision(uuid,uuid,uuid,uuid,text) TO tabletop_app;

CREATE FUNCTION sim.finish_campaign_revision(w uuid,b uuid,request uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,sim AS $$
BEGIN
  UPDATE sim.campaign_revision_commits c SET committed_at=clock_timestamp()
  WHERE (c.world_id,c.source_branch_id,c.request_id)=(w,b,request)
    AND sim.restoring_campaign_branch(w,c.branch_id)
    AND EXISTS (
      SELECT 1 FROM sim.branch_projections p JOIN sim.snapshots s
        ON (s.world_id,s.source_branch_id,s.projection_version,s.state_hash)=
           (p.world_id,p.branch_id,p.version,p.state_hash)
      JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(c.world_id,c.branch_id,c.run_id)
      WHERE (p.world_id,p.branch_id,p.state_hash)=(c.world_id,c.branch_id,c.state_hash)
        AND s.through_event_seq=0 AND r.run_kind='LIVE' AND r.status='PAUSED'
    );
  IF NOT FOUND THEN
    RAISE EXCEPTION 'the new continuation is incomplete' USING ERRCODE='23514';
  END IF;
END;
$$;
REVOKE ALL ON FUNCTION sim.finish_campaign_revision(uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sim.finish_campaign_revision(uuid,uuid,uuid) TO tabletop_app;

CREATE FUNCTION sim.require_committed_campaign_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM sim.campaign_revision_commits c
    WHERE (c.world_id,c.source_branch_id,c.request_id)=
      (NEW.world_id,NEW.source_branch_id,NEW.request_id) AND c.committed_at IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'campaign revision did not finish in the activation transaction'
      USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION sim.require_committed_campaign_revision() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER complete_revision_transaction
  AFTER INSERT ON sim.campaign_revision_commits DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION sim.require_committed_campaign_revision();

CREATE POLICY retained_campaign_events ON sim.events FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id) AND idempotency_key IS NULL);
CREATE POLICY retained_campaign_perceptions ON sim.event_perceptions FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));
CREATE POLICY retained_campaign_bindings ON tabletop.character_bindings FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));
CREATE POLICY retained_campaign_relationship_changes ON cognition.relationship_changes FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));
CREATE POLICY retained_campaign_checkpoint_rules ON sim.campaign_checkpoint_rules FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));
CREATE POLICY active_campaign_clock_leases ON sim.world_due_work AS RESTRICTIVE FOR UPDATE
  USING (sim.can_mutate_branch(world_id,branch_id))
  WITH CHECK (sim.can_mutate_branch(world_id,branch_id));

CREATE TABLE sim.campaign_revision_event_origins (
  world_id uuid NOT NULL,
  source_branch_id uuid NOT NULL,
  source_event_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  event_id uuid NOT NULL,
  PRIMARY KEY (world_id,branch_id,event_id),
  UNIQUE (world_id,branch_id,source_event_id),
  FOREIGN KEY (world_id,source_branch_id,source_event_id)
    REFERENCES sim.events(world_id,branch_id,event_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id,branch_id,event_id)
    REFERENCES sim.events(world_id,branch_id,event_id) ON DELETE RESTRICT
);
ALTER TABLE sim.campaign_revision_event_origins ENABLE ROW LEVEL SECURITY;
ALTER TABLE sim.campaign_revision_event_origins FORCE ROW LEVEL SECURITY;
CREATE POLICY campaign_revision_event_origin_read ON sim.campaign_revision_event_origins
  FOR SELECT USING (sim.can_read_campaign_checkpoint(world_id));
CREATE POLICY campaign_revision_event_origin_create ON sim.campaign_revision_event_origins
  FOR INSERT WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));
REVOKE ALL ON sim.campaign_revision_event_origins FROM PUBLIC,tabletop_app;
GRANT SELECT,INSERT ON sim.campaign_revision_event_origins TO tabletop_app;

CREATE FUNCTION cognition.retained_behavior_source(
  w uuid,b uuid,retained_event uuid,player uuid,body uuid,character_card uuid,
  content jsonb,movement boolean
) RETURNS boolean LANGUAGE sql STABLE SET search_path=pg_catalog,cognition,sim AS $$
  SELECT EXISTS (
    SELECT 1 FROM sim.campaign_revision_event_origins origin
    JOIN (
      SELECT world_id,branch_id,event_id,player_actor_id,entity_id,character_id,payload
      FROM cognition.human_movement_evidence WHERE movement
      UNION ALL
      SELECT world_id,branch_id,event_id,player_actor_id,entity_id,character_id,payload
      FROM cognition.human_choice_evidence WHERE NOT movement
    ) original ON (original.world_id,original.branch_id,original.event_id)=
      (origin.world_id,origin.source_branch_id,origin.source_event_id)
    WHERE (origin.world_id,origin.branch_id,origin.event_id)=(w,b,retained_event)
      AND (original.player_actor_id,original.entity_id,original.character_id)=
          (player,body,character_card)
      AND (original.payload - ARRAY['branch_id','run_id','binding_id']) =
          (content - ARRAY['branch_id','run_id','binding_id'])
  )
$$;
REVOKE ALL ON FUNCTION cognition.retained_behavior_source(uuid,uuid,uuid,uuid,uuid,uuid,jsonb,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cognition.retained_behavior_source(uuid,uuid,uuid,uuid,uuid,uuid,jsonb,boolean) TO tabletop_app;
CREATE POLICY retained_campaign_movement ON cognition.human_movement_evidence FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));
CREATE POLICY retained_campaign_choice ON cognition.human_choice_evidence FOR INSERT
  WITH CHECK (sim.restoring_campaign_branch(world_id,branch_id));

CREATE OR REPLACE FUNCTION cognition.guard_human_movement() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim,cognition AS $$
BEGIN
  IF sim.restoring_campaign_branch(NEW.world_id,NEW.branch_id) THEN
    IF NOT cognition.retained_behavior_source(
      NEW.world_id,NEW.branch_id,NEW.event_id,NEW.player_actor_id,NEW.entity_id,
      NEW.character_id,NEW.payload,true
    ) THEN RAISE EXCEPTION 'retained behavior must match the original human choice'
        USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM sim.events e JOIN sim.command_log c
      ON (c.run_id,c.actor_id,c.idempotency_key)=(e.run_id,e.actor_id,e.idempotency_key)
    JOIN sim.actors a ON a.id=e.actor_id
    JOIN sim.runs r ON r.id=e.run_id AND r.world_id=e.world_id AND r.branch_id=e.branch_id
    JOIN sim.branches b ON b.id=e.branch_id AND b.world_id=e.world_id
    WHERE e.event_id=NEW.event_id AND e.world_id=NEW.world_id AND e.branch_id=NEW.branch_id
      AND e.run_id=NEW.run_id AND e.embodied_entity_id=NEW.entity_id
      AND e.actor_id=NEW.player_actor_id AND e.decision_trace_id IS NULL
      AND c.command_type='tabletop.spatial.move' AND c.decision_authorship='HUMAN'
      AND c.input_origin='HUMAN_INPUT' AND a.actor_kind='HUMAN'
      AND r.run_kind='LIVE' AND b.branch_kind='CANONICAL'
  ) THEN RAISE EXCEPTION 'human evidence requires a matching committed human movement'; END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.payload#>'{frame,options}') o
    WHERE NOT COALESCE(o->>'direction' IN ('north','east','south','west')
      AND (o->>'approach')::numeric BETWEEN -1 AND 1,false))
    OR (SELECT count(DISTINCT o->>'direction') FROM jsonb_array_elements(NEW.payload#>'{frame,options}') o)<>4
  THEN RAISE EXCEPTION 'invalid movement options'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION cognition.guard_human_choice() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim,cognition AS $$
BEGIN
  IF sim.restoring_campaign_branch(NEW.world_id,NEW.branch_id) THEN
    IF NOT cognition.retained_behavior_source(
      NEW.world_id,NEW.branch_id,NEW.event_id,NEW.player_actor_id,NEW.entity_id,
      NEW.character_id,NEW.payload,false
    ) THEN RAISE EXCEPTION 'retained behavior must match the original human choice'
        USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM sim.events e JOIN sim.command_log c
      ON (c.run_id,c.actor_id,c.idempotency_key)=(e.run_id,e.actor_id,e.idempotency_key)
    JOIN sim.actors a ON a.id=e.actor_id
    JOIN sim.runs r ON (r.world_id,r.branch_id,r.id)=(e.world_id,e.branch_id,e.run_id)
    JOIN sim.branches b ON (b.world_id,b.id)=(e.world_id,e.branch_id)
    WHERE (e.world_id,e.branch_id,e.run_id,e.embodied_entity_id,e.actor_id,e.event_id)=
      (NEW.world_id,NEW.branch_id,NEW.run_id,NEW.entity_id,NEW.player_actor_id,NEW.event_id)
      AND e.decision_trace_id IS NULL AND c.decision_authorship='HUMAN'
      AND c.input_origin='HUMAN_INPUT' AND a.actor_kind='HUMAN'
      AND r.run_kind='LIVE' AND b.branch_kind='CANONICAL'
      AND ((c.command_type='tabletop.combat.attack' AND NEW.payload->>'chosen_key'='attack:'||(c.parameters->>'target_id'))
        OR (c.command_type='tabletop.spatial.move' AND NEW.payload->>'chosen_key'='move:'||(c.parameters->>'dx')||','||(c.parameters->>'dy'))
        OR (c.command_type='tabletop.dialogue.speak' AND c.parameters->>'language'='common'
            AND NEW.payload->>'chosen_key' LIKE 'speech:%:'||(c.parameters->>'volume')))
  ) THEN RAISE EXCEPTION 'choice evidence requires a matching committed human action'; END IF;
  IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.payload->'options') o WHERE o->>'key'=NEW.payload->>'chosen_key')
  THEN RAISE EXCEPTION 'chosen action is absent from perceived options'; END IF;
  RETURN NEW;
END $$;


CREATE OR REPLACE FUNCTION population.guard_embodied_source() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,population,sim AS $$
BEGIN
  IF TG_OP <> 'INSERT' AND OLD.binding_event_id IS NOT NULL THEN
    RAISE EXCEPTION 'embodied population source is immutable' USING ERRCODE='23514';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  IF NEW.binding_event_id IS NOT NULL THEN
    IF TG_OP = 'INSERT' AND sim.restoring_campaign_branch(NEW.world_id,NEW.branch_id)
      AND EXISTS (
        SELECT 1 FROM sim.campaign_revision_event_origins origin
        JOIN population.materialized_people source ON
          (source.world_id,source.branch_id,source.binding_event_id) =
          (origin.world_id,origin.source_branch_id,origin.source_event_id)
        WHERE (origin.world_id,origin.branch_id,origin.event_id) =
          (NEW.world_id,NEW.branch_id,NEW.binding_event_id)
          AND (source.persona_id,source.entity_id,source.binding_source_hash) =
          (NEW.persona_id,NEW.entity_id,NEW.binding_source_hash)
      ) THEN RETURN NEW; END IF;
    IF TG_OP <> 'UPDATE' THEN
      RAISE EXCEPTION 'binding requires a materialized source' USING ERRCODE='23514';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['entity_id', 'binding_event_id', 'binding_source_hash'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['entity_id', 'binding_event_id', 'binding_source_hash']) THEN
      RAISE EXCEPTION 'binding cannot change source state' USING ERRCODE='23514';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM sim.events event
      JOIN sim.command_log command
        ON command.world_id = event.world_id AND command.branch_id = event.branch_id
       AND command.run_id = event.run_id AND command.actor_id = event.actor_id
       AND command.idempotency_key = event.idempotency_key
      WHERE event.event_id = NEW.binding_event_id
        AND event.world_id = NEW.world_id AND event.branch_id = NEW.branch_id
        AND event.event_type = 'tabletop.population.bind'
        AND command.command_type = 'tabletop.population.bind'
        AND command.parameters->>'population_id' = NEW.population_id::text
        AND event.payload->>'persona_id' = NEW.persona_id::text
        AND event.payload->>'entity_id' = NEW.entity_id::text
        AND (event.payload->>'version')::bigint = OLD.lifecycle_version + 1
    ) THEN
      RAISE EXCEPTION 'binding requires its committed scoped command event' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION population.guard_embodied_transition() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,population,sim AS $$
BEGIN
  IF sim.restoring_campaign_branch(NEW.world_id,NEW.branch_id) THEN RETURN NEW; END IF;
  PERFORM 1 FROM population.materialized_people
    WHERE population_id=NEW.population_id AND persona_id=NEW.persona_id FOR UPDATE;
  IF EXISTS (SELECT 1 FROM population.materialized_people
             WHERE population_id=NEW.population_id AND persona_id=NEW.persona_id
               AND binding_event_id IS NOT NULL) THEN
    RAISE EXCEPTION 'embodied lifecycle requires canonical commands' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
