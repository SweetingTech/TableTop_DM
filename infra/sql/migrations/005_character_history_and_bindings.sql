-- Authored card history is private source material, never sensory evidence.
CREATE FUNCTION tabletop.character_card_content(document jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
  SELECT jsonb_build_object(
    'schema', 'character-card-1.0.0', 'name', document->'name',
    'species', document->'species', 'class_name', document->'class_name',
    'background', document->'background', 'level', document->'level',
    'ability_scores', document->'ability_scores',
    'authored_identity', jsonb_build_object(
      'backstory', COALESCE(document#>'{sheet,_authored_identity_v1,backstory}', '""'::jsonb),
      'motives', COALESCE(document#>'{sheet,_authored_identity_v1,motives}', '[]'::jsonb),
      'values', COALESCE(document#>'{sheet,_authored_identity_v1,values}', '[]'::jsonb),
      'bonds', COALESCE(document#>'{sheet,_authored_identity_v1,bonds}', '[]'::jsonb),
      'secrets', COALESCE(document#>'{sheet,_authored_identity_v1,secrets}', '[]'::jsonb),
      'initial_known_facts', COALESCE(document#>'{sheet,_authored_identity_v1,initial_known_facts}', '[]'::jsonb)
    )
  )
$$;

CREATE TABLE tabletop.character_card_revisions (
  revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  character_id uuid NOT NULL REFERENCES tabletop.characters(id) ON DELETE CASCADE,
  revision_number integer NOT NULL CHECK (revision_number > 0),
  content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (character_id, revision_number),
  UNIQUE (character_id, revision_id)
);

-- Backfill before forced RLS; an upgrade retains the current card as revision 1.
INSERT INTO tabletop.character_card_revisions(character_id, revision_number, content, recorded_at)
SELECT id, 1, tabletop.character_card_content(to_jsonb(c)), updated_at FROM tabletop.characters c;

CREATE FUNCTION tabletop.archive_character_card() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, tabletop AS $$
DECLARE next_content jsonb; previous_content jsonb; next_number integer;
BEGIN
  next_content := tabletop.character_card_content(to_jsonb(NEW));
  SELECT content, revision_number + 1 INTO previous_content, next_number
    FROM tabletop.character_card_revisions WHERE character_id = NEW.id
    ORDER BY revision_number DESC LIMIT 1;
  IF previous_content IS DISTINCT FROM next_content THEN
    -- The migration owner may be a superuser. SECURITY DEFINER must therefore
    -- check consent explicitly rather than relying on the owner's RLS behavior.
    IF NOT tabletop.can_edit_character_card(NEW.id) THEN
      RAISE EXCEPTION 'only the character owner or administrator can edit authored identity'
        USING ERRCODE = '42501';
    END IF;
    INSERT INTO tabletop.character_card_revisions(character_id, revision_number, content)
    VALUES (NEW.id, COALESCE(next_number, 1), next_content);
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER characters_archive_content AFTER INSERT OR UPDATE ON tabletop.characters
  FOR EACH ROW EXECUTE FUNCTION tabletop.archive_character_card();

CREATE FUNCTION tabletop.protect_card_revision() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, tabletop AS $$
BEGIN
  -- Explicit deletion of an unbound saved card also erases its private authored history.
  -- Bindings use RESTRICT below, so bound history cannot disappear under a live identity.
  IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 AND NOT EXISTS
    (SELECT 1 FROM tabletop.characters WHERE id = OLD.character_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'character card revisions are immutable';
END $$;
CREATE TRIGGER character_revisions_immutable BEFORE UPDATE OR DELETE
  ON tabletop.character_card_revisions FOR EACH ROW EXECUTE FUNCTION tabletop.protect_card_revision();

ALTER TABLE tabletop.character_card_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tabletop.character_card_revisions FORCE ROW LEVEL SECURITY;
CREATE FUNCTION tabletop.can_read_character_card(target_character_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, tabletop, identity, sim AS $$
  SELECT EXISTS (
    SELECT 1 FROM tabletop.characters c JOIN identity.users u
      ON u.actor_id = sim.current_actor_id() AND u.is_active
    WHERE c.id = target_character_id AND (
      c.owner_user_id = u.id OR EXISTS (SELECT 1 FROM identity.global_roles r WHERE r.user_id = u.id AND r.role = 'ADMIN')
      OR sim.has_world_capability(c.world_id, 'mind.read.all')
    )
  )
$$;
CREATE POLICY card_revisions_read ON tabletop.character_card_revisions FOR SELECT
  USING (tabletop.can_read_character_card(character_id));
CREATE FUNCTION tabletop.can_edit_character_card(target_character_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, tabletop, identity, sim AS $$
  SELECT EXISTS (
    SELECT 1 FROM tabletop.characters c JOIN identity.users u
      ON u.actor_id = sim.current_actor_id() AND u.is_active
    WHERE c.id = target_character_id AND (
      c.owner_user_id = u.id OR EXISTS (SELECT 1 FROM identity.global_roles r WHERE r.user_id = u.id AND r.role = 'ADMIN')
    )
  )
$$;
CREATE POLICY card_revisions_archive ON tabletop.character_card_revisions FOR INSERT
  WITH CHECK (tabletop.can_edit_character_card(character_id));
REVOKE ALL ON tabletop.character_card_revisions FROM PUBLIC, tabletop_app;
GRANT SELECT ON tabletop.character_card_revisions TO tabletop_app;
REVOKE ALL ON FUNCTION tabletop.archive_character_card(), tabletop.protect_card_revision() FROM PUBLIC;
REVOKE ALL ON FUNCTION tabletop.can_read_character_card(uuid), tabletop.character_card_content(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION tabletop.can_read_character_card(uuid) TO tabletop_app;
REVOKE ALL ON FUNCTION tabletop.can_edit_character_card(uuid) FROM PUBLIC;

CREATE FUNCTION tabletop.protect_character_history_owner() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, tabletop AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.id <> OLD.id OR NEW.owner_user_id <> OLD.owner_user_id THEN
      RAISE EXCEPTION 'character identity and owner are immutable';
    END IF;
    RETURN NEW;
  END IF;
  IF NOT tabletop.can_edit_character_card(OLD.id) THEN
    RAISE EXCEPTION 'only the character owner or administrator can delete authored history';
  END IF;
  RETURN OLD;
END $$;
CREATE TRIGGER character_history_owner BEFORE UPDATE OR DELETE ON tabletop.characters
  FOR EACH ROW EXECUTE FUNCTION tabletop.protect_character_history_owner();
REVOKE ALL ON FUNCTION tabletop.protect_character_history_owner() FROM PUBLIC;

-- Binding is versioned controller configuration, not a grant or a world-state command.
ALTER TABLE persona.compiled_profiles ADD CONSTRAINT compiled_profiles_purpose_identity_key
  UNIQUE (persona_id, persona_version_id, compiler_version, purpose);
CREATE TABLE tabletop.character_bindings (
  binding_id uuid PRIMARY KEY,
  sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  character_id uuid NOT NULL,
  card_revision_id uuid NOT NULL,
  world_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  run_id uuid NOT NULL,
  entity_id uuid NOT NULL,
  persona_id uuid NOT NULL,
  persona_version_id uuid NOT NULL,
  compiler_version text NOT NULL,
  purpose text NOT NULL DEFAULT 'CHARACTER' CHECK (purpose = 'CHARACTER'),
  replaces_binding_id uuid,
  recorded_by uuid NOT NULL REFERENCES sim.actors(id) ON DELETE RESTRICT,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (world_id, branch_id, run_id, entity_id, character_id, binding_id),
  FOREIGN KEY (character_id, card_revision_id)
    REFERENCES tabletop.character_card_revisions(character_id, revision_id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, run_id) REFERENCES sim.runs(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, entity_id) REFERENCES sim.entities(world_id, branch_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, entity_id) REFERENCES cognition.mind_states(world_id, branch_id, entity_id) ON DELETE RESTRICT,
  FOREIGN KEY (persona_id, persona_version_id, compiler_version, purpose)
    REFERENCES persona.compiled_profiles(persona_id, persona_version_id, compiler_version, purpose) ON DELETE RESTRICT,
  FOREIGN KEY (world_id, branch_id, run_id, entity_id, character_id, replaces_binding_id)
    REFERENCES tabletop.character_bindings(world_id, branch_id, run_id, entity_id, character_id, binding_id) ON DELETE RESTRICT
);
CREATE INDEX character_bindings_latest ON tabletop.character_bindings(world_id, branch_id, run_id, entity_id, sequence DESC);
CREATE TRIGGER character_bindings_append_only BEFORE UPDATE OR DELETE ON tabletop.character_bindings
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();
ALTER TABLE tabletop.character_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE tabletop.character_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY character_bindings_read ON tabletop.character_bindings FOR SELECT USING (
  sim.has_world_capability(world_id, 'mind.read.all') OR EXISTS (
    SELECT 1 FROM sim.entities e WHERE (e.world_id, e.branch_id, e.id) = (character_bindings.world_id, character_bindings.branch_id, character_bindings.entity_id)
      AND e.controller_actor_id = sim.current_actor_id()
  )
);
CREATE POLICY character_bindings_insert ON tabletop.character_bindings FOR INSERT WITH CHECK (
  recorded_by = sim.current_actor_id() AND sim.can_mutate_branch(world_id, branch_id)
  AND tabletop.can_read_character_card(character_id)
  AND (sim.has_world_capability(world_id, 'mind.write.all') OR (
    sim.has_world_capability(world_id, 'entity.act') AND EXISTS (
      SELECT 1 FROM sim.entities e WHERE (e.world_id, e.branch_id, e.id) = (character_bindings.world_id, character_bindings.branch_id, character_bindings.entity_id)
        AND e.controller_actor_id = sim.current_actor_id()
    )
  ))
);
REVOKE ALL ON tabletop.character_bindings FROM PUBLIC, tabletop_app;
GRANT SELECT, INSERT ON tabletop.character_bindings TO tabletop_app;
GRANT USAGE, SELECT ON SEQUENCE tabletop.character_bindings_sequence_seq TO tabletop_app;

CREATE FUNCTION tabletop.validate_character_binding() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, tabletop, sim AS $$
DECLARE previous tabletop.character_bindings;
BEGIN
  PERFORM id FROM sim.runs WHERE (world_id, branch_id, id) = (NEW.world_id, NEW.branch_id, NEW.run_id) FOR UPDATE;
  IF NOT EXISTS (SELECT 1 FROM tabletop.characters c WHERE c.id = NEW.character_id
    AND c.world_id = NEW.world_id AND c.entity_id = NEW.entity_id) THEN
    RAISE EXCEPTION 'character is not associated with this world and body';
  END IF;
  SELECT * INTO previous FROM tabletop.character_bindings WHERE
    (world_id,branch_id,run_id,entity_id) = (NEW.world_id,NEW.branch_id,NEW.run_id,NEW.entity_id)
    ORDER BY sequence DESC LIMIT 1;
  IF previous.binding_id IS DISTINCT FROM NEW.replaces_binding_id THEN
    RAISE EXCEPTION 'character binding changed; reload before replacing it';
  END IF;
  IF previous.character_id IS NOT NULL AND previous.character_id <> NEW.character_id THEN
    RAISE EXCEPTION 'body already represents another character';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER character_binding_lineage BEFORE INSERT ON tabletop.character_bindings
  FOR EACH ROW EXECUTE FUNCTION tabletop.validate_character_binding();
REVOKE ALL ON FUNCTION tabletop.validate_character_binding() FROM PUBLIC;
