-- Let campaign purge/import-replace delete the campaign root and rely on
-- database-owned referential actions instead of duplicated application SQL.

ALTER TABLE state.campaign_settings
  ALTER COLUMN embedding_model DROP NOT NULL;

DO $$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ('state', 'campaign_members', 'campaign_members_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'entities', 'entities_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'maps', 'maps_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'sessions', 'sessions_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'encounters', 'encounters_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'encounters', 'encounters_session_id_fkey', 'session_id', 'state', 'sessions', 'id', 'CASCADE'),
      ('state', 'intents', 'intents_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'intents', 'intents_session_id_fkey', 'session_id', 'state', 'sessions', 'id', 'CASCADE'),
      ('state', 'intents', 'intents_encounter_id_fkey', 'encounter_id', 'state', 'encounters', 'id', 'SET NULL'),
      ('state', 'intents', 'intents_entity_id_fkey', 'entity_id', 'state', 'entities', 'id', 'SET NULL'),
      ('state', 'interventions', 'interventions_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'interventions', 'interventions_session_id_fkey', 'session_id', 'state', 'sessions', 'id', 'CASCADE'),
      ('state', 'interventions', 'interventions_target_entity_id_fkey', 'target_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'encounter_slots', 'encounter_slots_encounter_id_fkey', 'encounter_id', 'state', 'encounters', 'id', 'CASCADE'),
      ('state', 'encounter_slots', 'encounter_slots_entity_id_fkey', 'entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'conditions', 'conditions_encounter_id_fkey', 'encounter_id', 'state', 'encounters', 'id', 'CASCADE'),
      ('state', 'conditions', 'conditions_entity_id_fkey', 'entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'reactions', 'reactions_intent_id_fkey', 'intent_id', 'state', 'intents', 'id', 'CASCADE'),
      ('state', 'divine_standings', 'divine_standings_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'divine_standings', 'divine_standings_god_entity_id_fkey', 'god_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'reaction_triggers', 'reaction_triggers_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'reaction_triggers', 'reaction_triggers_entity_id_fkey', 'entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'factions', 'factions_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'faction_memberships', 'faction_memberships_faction_id_fkey', 'faction_id', 'state', 'factions', 'id', 'CASCADE'),
      ('state', 'faction_memberships', 'faction_memberships_entity_id_fkey', 'entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'bounties', 'bounties_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'bounties', 'bounties_target_entity_id_fkey', 'target_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'bounties', 'bounties_issuer_faction_id_fkey', 'issuer_faction_id', 'state', 'factions', 'id', 'CASCADE'),
      ('state', 'faction_wars', 'faction_wars_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'faction_wars', 'faction_wars_faction_a_id_fkey', 'faction_a_id', 'state', 'factions', 'id', 'CASCADE'),
      ('state', 'faction_wars', 'faction_wars_faction_b_id_fkey', 'faction_b_id', 'state', 'factions', 'id', 'CASCADE'),
      ('state', 'location_metrics', 'location_metrics_location_entity_id_fkey', 'location_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'shops', 'shops_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'shops', 'shops_location_entity_id_fkey', 'location_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'shop_inventory', 'shop_inventory_shop_id_fkey', 'shop_id', 'state', 'shops', 'id', 'CASCADE'),
      ('state', 'shop_inventory', 'shop_inventory_item_entity_id_fkey', 'item_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'price_modifiers', 'price_modifiers_campaign_id_fkey', 'campaign_id', 'state', 'campaigns', 'id', 'CASCADE'),
      ('state', 'property_ownership', 'property_ownership_property_entity_id_fkey', 'property_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'property_ownership', 'property_ownership_owner_entity_id_fkey', 'owner_entity_id', 'state', 'entities', 'id', 'CASCADE'),
      ('state', 'map_nodes', 'map_nodes_map_id_fkey', 'map_id', 'state', 'maps', 'id', 'CASCADE'),
      ('state', 'entity_death_history', 'entity_death_history_revived_in_session_id_fkey', 'revived_in_session_id', 'state', 'sessions', 'id', 'SET NULL')
    ) AS v(schema_name, table_name, constraint_name, column_name, ref_schema, ref_table, ref_column, on_delete)
  LOOP
    EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I', spec.schema_name, spec.table_name, spec.constraint_name);
    EXECUTE format(
      'ALTER TABLE %I.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES %I.%I(%I) ON DELETE %s',
      spec.schema_name,
      spec.table_name,
      spec.constraint_name,
      spec.column_name,
      spec.ref_schema,
      spec.ref_table,
      spec.ref_column,
      spec.on_delete
    );
  END LOOP;
END $$;
