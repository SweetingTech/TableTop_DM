-- Phase 4.1 Demo Seed Data
-- Idempotent inserts for a ready-to-run scenario.

INSERT INTO state.campaigns (id, slug, name, status, mode)
VALUES (
  '11111111-1111-1111-1111-111111111111',
  'demo-eclipse-keep',
  'Demo: Eclipse Keep',
  'ACTIVE',
  'COMBAT'
)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug,
    name = EXCLUDED.name,
    status = EXCLUDED.status,
    mode = EXCLUDED.mode,
    updated_at = now();

INSERT INTO state.principals (id, principal_type, display_name, auth_subject, is_active)
VALUES
  ('22222222-2222-2222-2222-222222222221', 'AI_DM',  'DM',       'demo:dm',       true),
  ('22222222-2222-2222-2222-222222222222', 'HUMAN',  'PlayerA',  'demo:player_a', true),
  ('22222222-2222-2222-2222-222222222223', 'HUMAN',  'PlayerB',  'demo:player_b', true),
  ('22222222-2222-2222-2222-222222222224', 'AI_GOD', 'God1',     'demo:god1',     true),
  ('22222222-2222-2222-2222-222222222225', 'AI_NPC', 'NPCAgent', 'demo:npcagent', true)
ON CONFLICT (id) DO UPDATE
SET principal_type = EXCLUDED.principal_type,
    display_name = EXCLUDED.display_name,
    auth_subject = EXCLUDED.auth_subject,
    is_active = EXCLUDED.is_active,
    updated_at = now();

INSERT INTO state.campaign_members (campaign_id, principal_id, role)
VALUES
  ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222221', 'GM'),
  ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222', 'PLAYER'),
  ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222223', 'PLAYER'),
  ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222224', 'GOD_OPERATOR'),
  ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222225', 'OBSERVER')
ON CONFLICT (campaign_id, principal_id) DO UPDATE
SET role = EXCLUDED.role;
INSERT INTO state.entities (
  id, campaign_id, entity_type, name, tags, public_sheet, secret_sheet,
  hp_current, hp_max, ac, speed, controlled_by, controller_principal_id
)
VALUES
  (
    '33333333-3333-3333-3333-333333333331',
    '11111111-1111-1111-1111-111111111111',
    'PC',
    'Aria of Emberwatch',
    ARRAY['pc','party_alpha','melee'],
    '{"class":"fighter","level":3,"proficiencies":["swords","athletics"]}'::jsonb,
    '{"notes":"Receives secret dreams from the moon altar."}'::jsonb,
    28, 28, 16, 30,
    'PLAYER',
    '22222222-2222-2222-2222-222222222222'
  ),
  (
    '33333333-3333-3333-3333-333333333332',
    '11111111-1111-1111-1111-111111111111',
    'PC',
    'Bram Ironquill',
    ARRAY['pc','party_alpha','ranged'],
    '{"class":"ranger","level":3,"proficiencies":["bows","survival"]}'::jsonb,
    '{"notes":"Knows the hidden vault route under the keep."}'::jsonb,
    24, 24, 15, 30,
    'PLAYER',
    '22222222-2222-2222-2222-222222222223'
  ),
  (
    '33333333-3333-3333-3333-333333333333',
    '11111111-1111-1111-1111-111111111111',
    'NPC',
    'Ashfang Scout',
    ARRAY['npc','enemy','scout'],
    '{"role":"skirmisher","xp":100}'::jsonb,
    '{"ai_directive":"Delay intruders and report to commander."}'::jsonb,
    18, 18, 13, 35,
    'AI_NPC',
    '22222222-2222-2222-2222-222222222225'
  ),
  (
    '33333333-3333-3333-3333-333333333334',
    '11111111-1111-1111-1111-111111111111',
    'LOCATION',
    'Eclipse Keep Entry Hall',
    ARRAY['location','map_room','stone'],
    '{"description":"A ruined hall with collapsed pillars and moonlit skylight."}'::jsonb,
    '{"hidden_features":["tripwire at north arch","concealed altar switch"]}'::jsonb,
    NULL, NULL, NULL, NULL,
    'SYSTEM',
    NULL
  )
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    tags = EXCLUDED.tags,
    public_sheet = EXCLUDED.public_sheet,
    secret_sheet = EXCLUDED.secret_sheet,
    hp_current = EXCLUDED.hp_current,
    hp_max = EXCLUDED.hp_max,
    ac = EXCLUDED.ac,
    speed = EXCLUDED.speed,
    controlled_by = EXCLUDED.controlled_by,
    controller_principal_id = EXCLUDED.controller_principal_id,
    updated_at = now();

INSERT INTO state.maps (id, campaign_id, name, width, height, grid_size)
VALUES (
  '44444444-4444-4444-4444-444444444441',
  '11111111-1111-1111-1111-111111111111',
  'Eclipse Keep Ground Floor',
  20,
  20,
  5
)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    width = EXCLUDED.width,
    height = EXCLUDED.height,
    grid_size = EXCLUDED.grid_size,
    updated_at = now();

INSERT INTO state.map_nodes (id, map_id, tier, x, y, collision_mask, terrain)
VALUES
  ('44444444-4444-4444-4444-444444444451', '44444444-4444-4444-4444-444444444441', 0, 5, 5, B'0000000000000000', '{"type":"stone_floor"}'::jsonb),
  ('44444444-4444-4444-4444-444444444452', '44444444-4444-4444-4444-444444444441', 0, 6, 5, B'0000000000000001', '{"type":"rubble","difficult":true}'::jsonb),
  ('44444444-4444-4444-4444-444444444453', '44444444-4444-4444-4444-444444444441', 0, 7, 5, B'0000000000000000', '{"type":"stone_floor"}'::jsonb)
ON CONFLICT (map_id, tier, x, y) DO UPDATE
SET collision_mask = EXCLUDED.collision_mask,
    terrain = EXCLUDED.terrain;

INSERT INTO state.encounters (id, session_id, campaign_id, status, round_number, active_slot)
VALUES (
  '55555555-5555-5555-5555-555555555551',
  '66666666-6666-6666-6666-666666666661',
  '11111111-1111-1111-1111-111111111111',
  'ACTIVE',
  1,
  1
)
ON CONFLICT (id) DO UPDATE
SET session_id = EXCLUDED.session_id,
    status = EXCLUDED.status,
    round_number = EXCLUDED.round_number,
    active_slot = EXCLUDED.active_slot,
    updated_at = now();

INSERT INTO state.encounter_slots (id, encounter_id, entity_id, initiative, turn_order, is_active, ap_current)
VALUES
  ('55555555-5555-5555-5555-555555555561', '55555555-5555-5555-5555-555555555551', '33333333-3333-3333-3333-333333333331', 17, 1, true, 3),
  ('55555555-5555-5555-5555-555555555562', '55555555-5555-5555-5555-555555555551', '33333333-3333-3333-3333-333333333332', 14, 2, false, 3),
  ('55555555-5555-5555-5555-555555555563', '55555555-5555-5555-5555-555555555551', '33333333-3333-3333-3333-333333333333', 12, 3, false, 2)
ON CONFLICT (encounter_id, entity_id) DO UPDATE
SET initiative = EXCLUDED.initiative,
    turn_order = EXCLUDED.turn_order,
    is_active = EXCLUDED.is_active,
    ap_current = EXCLUDED.ap_current;

INSERT INTO state.reaction_triggers (id, campaign_id, entity_id, trigger_type, trigger_filter, action_template, priority, is_enabled)
VALUES (
  '77777777-7777-7777-7777-777777777771',
  '11111111-1111-1111-1111-111111111111',
  '33333333-3333-3333-3333-333333333333',
  'ON_MOVEMENT',
  '{"distance_lte":1,"faction":"enemy"}'::jsonb,
  '{"action_type":"OPPORTUNITY_ATTACK","weapon":"shortsword"}'::jsonb,
  10,
  true
)
ON CONFLICT (id) DO UPDATE
SET trigger_filter = EXCLUDED.trigger_filter,
    action_template = EXCLUDED.action_template,
    priority = EXCLUDED.priority,
    is_enabled = EXCLUDED.is_enabled;
