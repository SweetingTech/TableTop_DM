CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS state;

CREATE TABLE IF NOT EXISTS state.campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text UNIQUE NOT NULL,
  name text NOT NULL,
  status text NOT NULL CHECK (status IN ('DRAFT','ACTIVE','PAUSED','ENDED','ARCHIVED','TOMBSTONED','PURGED')),
  mode text NOT NULL CHECK (mode IN ('EXPLORATION','SOCIAL','COMBAT','CUTSCENE','PAUSED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON state.campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_mode ON state.campaigns(mode);

CREATE TABLE IF NOT EXISTS state.principals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  principal_type text NOT NULL CHECK (principal_type IN ('HUMAN','AI_DM','AI_NPC','AI_GOD','SYSTEM')),
  display_name text NOT NULL,
  auth_subject text UNIQUE NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_principals_type_active ON state.principals(principal_type, is_active);

CREATE TABLE IF NOT EXISTS state.campaign_members (
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  principal_id uuid NOT NULL REFERENCES state.principals(id),
  role text NOT NULL CHECK (role IN ('GM','PLAYER','OBSERVER','GOD_OPERATOR','SYSTEM')),
  joined_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (campaign_id, principal_id)
);
CREATE INDEX IF NOT EXISTS idx_campaign_members_principal_campaign ON state.campaign_members(principal_id, campaign_id);

CREATE TABLE IF NOT EXISTS state.entities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  entity_type text NOT NULL,
  name text NOT NULL,
  tags text[] NOT NULL DEFAULT '{}'::text[],
  public_sheet jsonb NOT NULL DEFAULT '{}'::jsonb,
  secret_sheet jsonb NOT NULL DEFAULT '{}'::jsonb,
  hp_current int,
  hp_max int,
  ac int,
  speed int,
  controlled_by text NOT NULL,
  controller_principal_id uuid REFERENCES state.principals(id),
  control_version bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (hp_max IS NULL OR hp_current IS NULL OR hp_current <= hp_max)
);
CREATE INDEX IF NOT EXISTS idx_entities_campaign_entity_type ON state.entities(campaign_id, entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_tags ON state.entities USING gin(tags);
CREATE INDEX IF NOT EXISTS idx_entities_public_sheet ON state.entities USING gin(public_sheet);
CREATE INDEX IF NOT EXISTS idx_entities_controller ON state.entities(controller_principal_id);

CREATE TABLE IF NOT EXISTS state.maps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  name text NOT NULL,
  width int NOT NULL,
  height int NOT NULL,
  grid_size int NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_maps_campaign ON state.maps(campaign_id);

CREATE TABLE IF NOT EXISTS state.map_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  map_id uuid NOT NULL REFERENCES state.maps(id),
  tier smallint NOT NULL,
  x int NOT NULL,
  y int NOT NULL,
  collision_mask bit(16) NOT NULL,
  terrain jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (map_id, tier, x, y)
);
CREATE INDEX IF NOT EXISTS idx_map_nodes_map_tier ON state.map_nodes(map_id, tier);
CREATE INDEX IF NOT EXISTS idx_map_nodes_map_xy ON state.map_nodes(map_id, x, y);

CREATE TABLE IF NOT EXISTS state.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  status text NOT NULL CHECK (status IN ('ACTIVE','PAUSED','ENDED')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  checkpoint_seq_id bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sessions_campaign_status ON state.sessions(campaign_id, status);

CREATE TABLE IF NOT EXISTS state.encounters (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES state.sessions(id),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  status text NOT NULL CHECK (status IN ('PENDING','ACTIVE','COMPLETED','ABORTED')),
  round_number int NOT NULL DEFAULT 0,
  active_slot int,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_encounters_campaign_status ON state.encounters(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_encounters_session_status ON state.encounters(session_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_encounters_active_per_session ON state.encounters(session_id)
WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS state.encounter_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  encounter_id uuid NOT NULL REFERENCES state.encounters(id),
  entity_id uuid NOT NULL REFERENCES state.entities(id),
  initiative int NOT NULL,
  turn_order int NOT NULL,
  is_active boolean NOT NULL DEFAULT false,
  ap_current int NOT NULL DEFAULT 0,
  UNIQUE (encounter_id, entity_id),
  UNIQUE (encounter_id, turn_order)
);
CREATE INDEX IF NOT EXISTS idx_encounter_slots_initiative ON state.encounter_slots(encounter_id, initiative DESC);

CREATE TABLE IF NOT EXISTS state.conditions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  encounter_id uuid NOT NULL REFERENCES state.encounters(id),
  entity_id uuid NOT NULL REFERENCES state.entities(id),
  condition_type text NOT NULL,
  stacks int NOT NULL DEFAULT 1,
  expires_at_round int,
  source_event_id uuid
);
CREATE INDEX IF NOT EXISTS idx_conditions_entity_type ON state.conditions(entity_id, condition_type);
CREATE INDEX IF NOT EXISTS idx_conditions_encounter_entity ON state.conditions(encounter_id, entity_id);

CREATE TABLE IF NOT EXISTS state.intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  session_id uuid NOT NULL REFERENCES state.sessions(id),
  encounter_id uuid REFERENCES state.encounters(id),
  principal_id uuid NOT NULL REFERENCES state.principals(id),
  entity_id uuid REFERENCES state.entities(id),
  intent_type text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL CHECK (status IN ('RECEIVED','VALIDATED','REJECTED','COMMITTED')),
  idempotency_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, principal_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_intents_encounter_status ON state.intents(encounter_id, status);
CREATE INDEX IF NOT EXISTS idx_intents_payload ON state.intents USING gin(payload);

CREATE TABLE IF NOT EXISTS state.reactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_id uuid NOT NULL REFERENCES state.intents(id),
  trigger_event_id uuid NOT NULL,
  principal_id uuid NOT NULL REFERENCES state.principals(id),
  reaction_type text NOT NULL,
  payload jsonb NOT NULL,
  stack_position int NOT NULL,
  status text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reactions_intent_stack ON state.reactions(intent_id, stack_position);
CREATE INDEX IF NOT EXISTS idx_reactions_trigger_event ON state.reactions(trigger_event_id);

CREATE TABLE IF NOT EXISTS state.interventions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  session_id uuid NOT NULL REFERENCES state.sessions(id),
  source_principal_id uuid NOT NULL REFERENCES state.principals(id),
  target_entity_id uuid NOT NULL REFERENCES state.entities(id),
  action_type text NOT NULL,
  authority_tier smallint NOT NULL,
  stack_group text NOT NULL,
  stack_mode text NOT NULL CHECK (stack_mode IN ('STACK','REPLACE','BLOCK')),
  active boolean NOT NULL DEFAULT true,
  starts_at timestamptz NOT NULL,
  ends_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_interventions_campaign_active ON state.interventions(campaign_id, active);
CREATE INDEX IF NOT EXISTS idx_interventions_target_active ON state.interventions(target_entity_id, active);
CREATE INDEX IF NOT EXISTS idx_interventions_stack_group_active ON state.interventions(stack_group, active);

CREATE TABLE IF NOT EXISTS state.divine_standings (
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  principal_id uuid NOT NULL REFERENCES state.principals(id),
  god_entity_id uuid NOT NULL REFERENCES state.entities(id),
  standing_score int NOT NULL DEFAULT 0,
  last_domain_tag text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (campaign_id, principal_id, god_entity_id)
);
CREATE INDEX IF NOT EXISTS idx_divine_standings_campaign_god_score ON state.divine_standings(campaign_id, god_entity_id, standing_score);

CREATE TABLE IF NOT EXISTS state.reaction_triggers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  entity_id uuid NOT NULL REFERENCES state.entities(id),
  trigger_type text NOT NULL,
  trigger_filter jsonb NOT NULL,
  action_template jsonb NOT NULL,
  priority int NOT NULL DEFAULT 0,
  is_enabled boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_reaction_triggers_entity_type_enabled ON state.reaction_triggers(entity_id, trigger_type, is_enabled);
CREATE INDEX IF NOT EXISTS idx_reaction_triggers_filter ON state.reaction_triggers USING gin(trigger_filter);

CREATE TABLE IF NOT EXISTS state.factions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  faction_type text NOT NULL CHECK (faction_type IN ('FACTION','GUILD','PATRON_ORDER')),
  name text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (campaign_id, name)
);

CREATE TABLE IF NOT EXISTS state.faction_memberships (
  faction_id uuid NOT NULL REFERENCES state.factions(id),
  entity_id uuid NOT NULL REFERENCES state.entities(id),
  rank text NOT NULL,
  joined_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (faction_id, entity_id)
);

CREATE TABLE IF NOT EXISTS state.bounties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  target_entity_id uuid NOT NULL REFERENCES state.entities(id),
  issuer_faction_id uuid NOT NULL REFERENCES state.factions(id),
  amount numeric(12,2) NOT NULL,
  status text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bounties_campaign_status ON state.bounties(campaign_id, status);
CREATE INDEX IF NOT EXISTS idx_bounties_target_status ON state.bounties(target_entity_id, status);

CREATE TABLE IF NOT EXISTS state.faction_wars (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  faction_a_id uuid NOT NULL REFERENCES state.factions(id),
  faction_b_id uuid NOT NULL REFERENCES state.factions(id),
  status text NOT NULL,
  started_at timestamptz NOT NULL,
  UNIQUE (campaign_id, faction_a_id, faction_b_id)
);

CREATE TABLE IF NOT EXISTS state.location_metrics (
  location_entity_id uuid PRIMARY KEY REFERENCES state.entities(id),
  stability int NOT NULL,
  scarcity_index numeric(5,2) NOT NULL,
  prosperity_index numeric(5,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS state.shops (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  location_entity_id uuid NOT NULL REFERENCES state.entities(id),
  name text NOT NULL,
  price_multiplier numeric(6,3) NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_shops_campaign_location ON state.shops(campaign_id, location_entity_id);

CREATE TABLE IF NOT EXISTS state.shop_inventory (
  shop_id uuid NOT NULL REFERENCES state.shops(id),
  item_entity_id uuid NOT NULL REFERENCES state.entities(id),
  quantity int NOT NULL,
  base_price numeric(12,2) NOT NULL,
  PRIMARY KEY (shop_id, item_entity_id)
);

CREATE TABLE IF NOT EXISTS state.price_modifiers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  scope_type text NOT NULL,
  scope_id uuid NOT NULL,
  modifier numeric(6,3) NOT NULL,
  reason text NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_modifiers_scope ON state.price_modifiers(campaign_id, scope_type, scope_id);

CREATE TABLE IF NOT EXISTS state.property_ownership (
  property_entity_id uuid PRIMARY KEY REFERENCES state.entities(id),
  owner_entity_id uuid NOT NULL REFERENCES state.entities(id),
  acquired_at timestamptz NOT NULL,
  upkeep_cost numeric(12,2) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_property_ownership_owner ON state.property_ownership(owner_entity_id);
