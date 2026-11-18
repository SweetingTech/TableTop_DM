-- Retained prose is derived presentation. Sources remain in the event and observation ledgers.
ALTER TABLE sim.events ADD CONSTRAINT events_narration_source_key
  UNIQUE (world_id, branch_id, run_id, event_id);
ALTER TABLE cognition.observations ADD CONSTRAINT observations_narration_source_key
  UNIQUE (world_id, branch_id, observer_entity_id, source_event_id, id);

CREATE TABLE cognition.narration_entries (
  narration_id uuid PRIMARY KEY,
  requester_actor_id uuid NOT NULL REFERENCES sim.actors(id),
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  audience text NOT NULL CHECK (audience IN ('OPERATOR', 'SPECTATOR', 'CHARACTER')),
  observer_entity_id uuid,
  source_event_id uuid NOT NULL,
  source_observation_id uuid,
  occurred_at timestamptz NOT NULL,
  version text NOT NULL CHECK (length(btrim(version)) BETWEEN 1 AND 120),
  text text NOT NULL CHECK (length(text) BETWEEN 1 AND 850),
  CHECK (
    (audience = 'OPERATOR' AND observer_entity_id IS NULL AND source_observation_id IS NULL)
    OR (audience <> 'OPERATOR' AND observer_entity_id IS NOT NULL AND source_observation_id IS NOT NULL)
  ),
  FOREIGN KEY (world_id, branch_id, run_id, source_event_id)
    REFERENCES sim.events(world_id, branch_id, run_id, event_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, observer_entity_id, source_event_id, source_observation_id)
    REFERENCES cognition.observations(world_id, branch_id, observer_entity_id, source_event_id, id)
    ON DELETE RESTRICT,
  FOREIGN KEY (source_event_id, observer_entity_id)
    REFERENCES sim.event_perceptions(event_id, observer_entity_id) ON DELETE RESTRICT
);

CREATE TRIGGER narration_entries_append_only BEFORE UPDATE OR DELETE ON cognition.narration_entries
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

ALTER TABLE cognition.narration_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE cognition.narration_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY narration_entries_access ON cognition.narration_entries
  USING (
    requester_actor_id = (SELECT sim.current_actor_id())
    AND sim.has_world_capability(world_id, 'world.read')
    AND (
      sim.has_world_capability(world_id, 'world.read.all')
      OR (audience <> 'OPERATOR' AND (
        sim.has_world_capability(world_id, 'mind.read.all')
        OR sim.runtime_controls_entity(world_id, branch_id, observer_entity_id)
        OR EXISTS (
          SELECT 1 FROM sim.entities entity
          WHERE (entity.world_id, entity.branch_id, entity.id) =
                (narration_entries.world_id, narration_entries.branch_id, observer_entity_id)
            AND entity.controller_actor_id = (SELECT sim.current_actor_id())
        )
      ))
    )
    AND (audience <> 'SPECTATOR' OR EXISTS (
      SELECT 1 FROM sim.event_perceptions perception
      WHERE (perception.event_id, perception.observer_entity_id) =
            (narration_entries.source_event_id, narration_entries.observer_entity_id)
        AND 'SIGHT' = ANY(perception.modalities)
    ))
  );
REVOKE ALL ON cognition.narration_entries FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT ON cognition.narration_entries TO tabletop_app;
