# STATE_DB_SCHEMA
Status: Phase 2.1 logical schema specification (Postgres, `state` schema).

## Conventions
- UUID primary keys use `gen_random_uuid()`.
- `created_at`/`updated_at` are `timestamptz` (UTC).
- Soft-delete omitted for v1; deletions are explicit and audited in ledger.
- JSONB columns validated in service layer with strict schemas.

## campaigns
- `id` UUID PK
- `slug` text UNIQUE NOT NULL
- `name` text NOT NULL
- `status` text NOT NULL CHECK (`status` in ('DRAFT','ACTIVE','PAUSED','ENDED','ARCHIVED','TOMBSTONED','PURGED'))
- `mode` text NOT NULL CHECK (`mode` in ('EXPLORATION','SOCIAL','COMBAT','CUTSCENE','PAUSED'))
- timestamps
Indexes: `(status)`, `(mode)`.

## principals
- `id` UUID PK
- `principal_type` text NOT NULL CHECK in ('HUMAN','AI_DM','AI_NPC','AI_GOD','SYSTEM')
- `display_name` text NOT NULL
- `auth_subject` text UNIQUE NOT NULL
- `is_active` boolean NOT NULL default true
- timestamps
Indexes: `(principal_type, is_active)`.

## campaign_members
- `campaign_id` UUID FK -> campaigns(id)
- `principal_id` UUID FK -> principals(id)
- `role` text NOT NULL CHECK in ('GM','PLAYER','OBSERVER','GOD_OPERATOR','SYSTEM')
- `joined_at` timestamptz NOT NULL default now()
PK: `(campaign_id, principal_id)`
Indexes: `(principal_id, campaign_id)`.

## entities
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id) NOT NULL
- `entity_type` text NOT NULL
- `name` text NOT NULL
- `tags` text[] NOT NULL default '{}'
- `public_sheet` jsonb NOT NULL default '{}'::jsonb
- `secret_sheet` jsonb NOT NULL default '{}'::jsonb
- perf fields: `hp_current` int, `hp_max` int, `ac` int, `speed` int
- control: `controlled_by` text NOT NULL, `controller_principal_id` UUID NULL FK -> principals(id), `control_version` bigint NOT NULL default 0
- timestamps
Constraints: `hp_current <= hp_max` when both non-null.
Indexes: `(campaign_id, entity_type)`, GIN on `tags`, GIN on `public_sheet`, `(controller_principal_id)`.

## maps
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `name` text NOT NULL
- `width` int NOT NULL
- `height` int NOT NULL
- `grid_size` int NOT NULL
- timestamps
Indexes: `(campaign_id)`.

## map_nodes
- `id` UUID PK
- `map_id` UUID FK -> maps(id)
- `tier` smallint NOT NULL
- `x` int NOT NULL
- `y` int NOT NULL
- `collision_mask` bit(16) NOT NULL
- `terrain` jsonb NOT NULL default '{}'::jsonb
UNIQUE: `(map_id, tier, x, y)`
Indexes: `(map_id, tier)`, `(map_id, x, y)`.

## encounters
- `id` UUID PK
- `session_id` UUID NOT NULL
- `campaign_id` UUID FK -> campaigns(id)
- `status` text NOT NULL CHECK in ('PENDING','ACTIVE','COMPLETED','ABORTED')
- `round_number` int NOT NULL default 0
- `active_slot` int NULL
- timestamps
Indexes: `(campaign_id, status)`, `(session_id, status)`.

## encounter_slots
- `id` UUID PK
- `encounter_id` UUID FK -> encounters(id)
- `entity_id` UUID FK -> entities(id)
- `initiative` int NOT NULL
- `turn_order` int NOT NULL
- `is_active` boolean NOT NULL default false
- `ap_current` int NOT NULL default 0
UNIQUE: `(encounter_id, entity_id)`, `(encounter_id, turn_order)`
Indexes: `(encounter_id, initiative DESC)`.

## conditions
- `id` UUID PK
- `encounter_id` UUID FK -> encounters(id)
- `entity_id` UUID FK -> entities(id)
- `condition_type` text NOT NULL
- `stacks` int NOT NULL default 1
- `expires_at_round` int NULL
- `source_event_id` UUID NULL
Indexes: `(entity_id, condition_type)`, `(encounter_id, entity_id)`.

## intents
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `session_id` UUID NOT NULL
- `encounter_id` UUID NULL FK -> encounters(id)
- `principal_id` UUID FK -> principals(id)
- `entity_id` UUID NULL FK -> entities(id)
- `intent_type` text NOT NULL
- `payload` jsonb NOT NULL
- `status` text NOT NULL CHECK in ('RECEIVED','VALIDATED','REJECTED','COMMITTED')
- `idempotency_key` text NOT NULL
- timestamps
UNIQUE: `(session_id, principal_id, idempotency_key)`
Indexes: `(encounter_id, status)`, GIN `(payload)`.

## reactions
- `id` UUID PK
- `intent_id` UUID FK -> intents(id)
- `trigger_event_id` UUID NOT NULL
- `principal_id` UUID FK -> principals(id)
- `reaction_type` text NOT NULL
- `payload` jsonb NOT NULL
- `stack_position` int NOT NULL
- `status` text NOT NULL
Indexes: `(intent_id, stack_position)`, `(trigger_event_id)`.

## interventions
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `session_id` UUID NOT NULL
- `source_principal_id` UUID FK -> principals(id)
- `target_entity_id` UUID FK -> entities(id)
- `action_type` text NOT NULL
- `authority_tier` smallint NOT NULL
- `stack_group` text NOT NULL
- `stack_mode` text NOT NULL CHECK in ('STACK','REPLACE','BLOCK')
- `active` boolean NOT NULL default true
- `starts_at` timestamptz NOT NULL
- `ends_at` timestamptz NULL
Indexes: `(campaign_id, active)`, `(target_entity_id, active)`, `(stack_group, active)`.

## divine_standings
- `campaign_id` UUID FK -> campaigns(id)
- `principal_id` UUID FK -> principals(id)
- `god_entity_id` UUID FK -> entities(id)
- `standing_score` int NOT NULL default 0
- `last_domain_tag` text NULL
- `updated_at` timestamptz NOT NULL default now()
PK: `(campaign_id, principal_id, god_entity_id)`
Indexes: `(campaign_id, god_entity_id, standing_score)`.

## reaction_triggers
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `entity_id` UUID FK -> entities(id)
- `trigger_type` text NOT NULL
- `trigger_filter` jsonb NOT NULL
- `action_template` jsonb NOT NULL
- `priority` int NOT NULL default 0
- `is_enabled` boolean NOT NULL default true
Indexes: `(entity_id, trigger_type, is_enabled)`, GIN `(trigger_filter)`.

## factions / guilds / membership / bounties / wars
### factions
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `faction_type` text NOT NULL CHECK in ('FACTION','GUILD','PATRON_ORDER')
- `name` text NOT NULL
- `metadata` jsonb NOT NULL default '{}'::jsonb
UNIQUE `(campaign_id, name)`

### faction_memberships
- `faction_id` UUID FK -> factions(id)
- `entity_id` UUID FK -> entities(id)
- `rank` text NOT NULL
- `joined_at` timestamptz NOT NULL default now()
PK `(faction_id, entity_id)`

### bounties
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `target_entity_id` UUID FK -> entities(id)
- `issuer_faction_id` UUID FK -> factions(id)
- `amount` numeric(12,2) NOT NULL
- `status` text NOT NULL
Indexes `(campaign_id, status)`, `(target_entity_id, status)`

### faction_wars
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `faction_a_id` UUID FK -> factions(id)
- `faction_b_id` UUID FK -> factions(id)
- `status` text NOT NULL
- `started_at` timestamptz NOT NULL
UNIQUE `(campaign_id, faction_a_id, faction_b_id)`

## economy tables
### location_metrics
- `location_entity_id` UUID PK FK -> entities(id)
- `stability` int NOT NULL
- `scarcity_index` numeric(5,2) NOT NULL
- `prosperity_index` numeric(5,2) NOT NULL

### shops
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `location_entity_id` UUID FK -> entities(id)
- `name` text NOT NULL
- `price_multiplier` numeric(6,3) NOT NULL default 1.0
Indexes `(campaign_id, location_entity_id)`

### shop_inventory
- `shop_id` UUID FK -> shops(id)
- `item_entity_id` UUID FK -> entities(id)
- `quantity` int NOT NULL
- `base_price` numeric(12,2) NOT NULL
PK `(shop_id, item_entity_id)`

### price_modifiers
- `id` UUID PK
- `campaign_id` UUID FK -> campaigns(id)
- `scope_type` text NOT NULL
- `scope_id` UUID NOT NULL
- `modifier` numeric(6,3) NOT NULL
- `reason` text NOT NULL
Indexes `(campaign_id, scope_type, scope_id)`

### property_ownership
- `property_entity_id` UUID PK FK -> entities(id)
- `owner_entity_id` UUID FK -> entities(id)
- `acquired_at` timestamptz NOT NULL
- `upkeep_cost` numeric(12,2) NOT NULL
Indexes `(owner_entity_id)`.
