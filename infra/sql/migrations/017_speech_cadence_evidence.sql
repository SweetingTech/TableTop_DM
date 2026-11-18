-- Cadence buckets extend the existing append-only evidence for committed human speech.
ALTER TABLE cognition.human_choice_evidence DROP CONSTRAINT human_choice_evidence_check;
ALTER TABLE cognition.human_choice_evidence ADD CONSTRAINT human_choice_evidence_check CHECK (
  COALESCE(payload->>'world_id'=world_id::text AND payload->>'branch_id'=branch_id::text
    AND payload->>'run_id'=run_id::text AND payload->>'entity_id'=entity_id::text
    AND payload->>'player_actor_id'=player_actor_id::text AND payload->>'character_id'=character_id::text
    AND payload->>'binding_id'=binding_id::text
    AND payload->>'version' IN (
      'speech-combat-behavior-1.0.0','speech-combat-behavior-1.1.0','speech-combat-behavior-1.2.0'
    )
    AND (payload->>'projection_version')::bigint>=0
    AND jsonb_typeof(payload->'frame')='object' AND jsonb_typeof(payload->'options')='array'
    AND jsonb_array_length(payload->'options') BETWEEN 1 AND
      CASE WHEN payload->>'version'='speech-combat-behavior-1.0.0' THEN 28 ELSE 40 END
    AND length(payload->>'chosen_key') BETWEEN 1 AND 100
    AND (CASE WHEN payload->>'version'='speech-combat-behavior-1.2.0'
      THEN payload->>'chosen_key' LIKE 'speech:%'
        AND payload->>'utterance_cadence' IN ('BRIEF','BALANCED','ELABORATE')
      ELSE NOT (payload ? 'utterance_cadence') END),false));
