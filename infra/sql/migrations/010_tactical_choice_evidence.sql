-- Extend new decision evidence while retaining the original immutable rows and profiles.
ALTER TABLE cognition.human_choice_evidence DROP CONSTRAINT human_choice_evidence_check;
ALTER TABLE cognition.human_choice_evidence ADD CONSTRAINT human_choice_evidence_check CHECK (
  COALESCE(payload->>'world_id'=world_id::text AND payload->>'branch_id'=branch_id::text
    AND payload->>'run_id'=run_id::text AND payload->>'entity_id'=entity_id::text
    AND payload->>'player_actor_id'=player_actor_id::text AND payload->>'character_id'=character_id::text
    AND payload->>'binding_id'=binding_id::text
    AND payload->>'version' IN ('speech-combat-behavior-1.0.0','speech-combat-behavior-1.1.0')
    AND (payload->>'projection_version')::bigint>=0
    AND jsonb_typeof(payload->'frame')='object' AND jsonb_typeof(payload->'options')='array'
    AND jsonb_array_length(payload->'options') BETWEEN 1 AND
      CASE WHEN payload->>'version'='speech-combat-behavior-1.0.0' THEN 28 ELSE 40 END
    AND length(payload->>'chosen_key') BETWEEN 1 AND 100,false));

CREATE OR REPLACE FUNCTION cognition.guard_human_choice() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,sim,cognition AS $$
BEGIN
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
          AND NEW.payload->>'chosen_key' LIKE 'speech:%:'||(c.parameters->>'volume'))
        OR (NEW.payload->>'version'='speech-combat-behavior-1.1.0' AND
          ((c.command_type='tabletop.combat.guard' AND NEW.payload->>'chosen_key'='guard')
           OR (c.command_type='tabletop.magic.invoke' AND NEW.payload->>'chosen_key'=
             'spell:'||(c.parameters->>'spell_id')||':'||(c.parameters->>'target_id')))))
  ) THEN RAISE EXCEPTION 'choice evidence requires a matching committed human action'; END IF;
  IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.payload->'options') o WHERE o->>'key'=NEW.payload->>'chosen_key')
  THEN RAISE EXCEPTION 'chosen action is absent from perceived options'; END IF;
  RETURN NEW;
END $$;
