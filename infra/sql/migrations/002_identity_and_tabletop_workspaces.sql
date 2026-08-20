-- Durable accounts, role-aware workspaces, player characters, and hosted games.

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS tabletop;
REVOKE ALL ON SCHEMA identity, tabletop FROM PUBLIC;

CREATE TABLE identity.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id uuid NOT NULL UNIQUE REFERENCES sim.actors(id) ON DELETE RESTRICT,
  username text NOT NULL CHECK (username ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$'),
  password_hash text NOT NULL CHECK (length(password_hash) BETWEEN 40 AND 1024),
  password_change_required boolean NOT NULL DEFAULT false,
  is_active boolean NOT NULL DEFAULT true,
  failed_login_count integer NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
  locked_until timestamptz,
  last_login_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_identity_users_username_ci ON identity.users(lower(username));

CREATE TABLE identity.user_profiles (
  user_id uuid PRIMARY KEY REFERENCES identity.users(id) ON DELETE CASCADE,
  display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 160),
  legal_name text,
  email text,
  date_of_birth date,
  pronouns text,
  timezone text NOT NULL DEFAULT 'UTC',
  locale text NOT NULL DEFAULT 'en-US',
  bio text,
  avatar_uri text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (email IS NULL OR length(btrim(email)) BETWEEN 3 AND 320),
  CHECK (pronouns IS NULL OR length(pronouns) <= 80),
  CHECK (bio IS NULL OR length(bio) <= 4000)
);

CREATE TABLE identity.global_roles (
  user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('ADMIN')),
  granted_by uuid REFERENCES identity.users(id) ON DELETE SET NULL,
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE identity.world_roles (
  world_id uuid NOT NULL REFERENCES sim.worlds(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('DM', 'PLAYER')),
  granted_by uuid REFERENCES identity.users(id) ON DELETE SET NULL,
  granted_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (world_id, user_id, role)
);
CREATE INDEX idx_identity_world_roles_user ON identity.world_roles(user_id, world_id);

CREATE TABLE identity.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  user_agent text,
  remote_address text,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CHECK (expires_at > created_at)
);
CREATE INDEX idx_identity_sessions_active
  ON identity.sessions(token_hash, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE identity.audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_user_id uuid REFERENCES identity.users(id) ON DELETE SET NULL,
  target_user_id uuid REFERENCES identity.users(id) ON DELETE SET NULL,
  event_type text NOT NULL CHECK (length(btrim(event_type)) BETWEEN 1 AND 120),
  details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
  occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER identity_audit_log_append_only
  BEFORE UPDATE OR DELETE ON identity.audit_log
  FOR EACH ROW EXECUTE FUNCTION infra_meta.reject_mutation();

CREATE TABLE tabletop.characters (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE RESTRICT,
  world_id uuid REFERENCES sim.worlds(id) ON DELETE SET NULL,
  entity_id uuid,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 160),
  species text NOT NULL CHECK (length(btrim(species)) BETWEEN 1 AND 100),
  class_name text NOT NULL CHECK (length(btrim(class_name)) BETWEEN 1 AND 100),
  background text NOT NULL DEFAULT 'Adventurer',
  level integer NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 20),
  status text NOT NULL DEFAULT 'ALIVE'
    CHECK (status IN ('ALIVE', 'DEAD', 'MISSING', 'RETIRED')),
  current_hit_points integer NOT NULL DEFAULT 1,
  maximum_hit_points integer NOT NULL DEFAULT 1 CHECK (maximum_hit_points > 0),
  armor_class integer NOT NULL DEFAULT 10 CHECK (armor_class BETWEEN 0 AND 99),
  speed integer NOT NULL DEFAULT 30 CHECK (speed BETWEEN 0 AND 999),
  ability_scores jsonb NOT NULL DEFAULT
    '{"strength":10,"dexterity":10,"constitution":10,"intelligence":10,"wisdom":10,"charisma":10}'::jsonb
    CHECK (jsonb_typeof(ability_scores) = 'object'),
  sheet jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(sheet) = 'object'),
  creation_method text NOT NULL DEFAULT 'BUILT'
    CHECK (creation_method IN ('BUILT', 'GENERATED', 'IMPORTED')),
  source_filename text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (current_hit_points BETWEEN 0 AND maximum_hit_points),
  CHECK (entity_id IS NULL OR world_id IS NOT NULL)
);
CREATE INDEX idx_tabletop_characters_owner ON tabletop.characters(owner_user_id, updated_at DESC);
CREATE INDEX idx_tabletop_characters_world ON tabletop.characters(world_id, status);

CREATE TABLE tabletop.games (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  world_id uuid NOT NULL REFERENCES sim.worlds(id) ON DELETE RESTRICT,
  host_user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE RESTRICT,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 160),
  description text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'PLANNING'
    CHECK (status IN ('PLANNING', 'LOBBY', 'LIVE', 'PAUSED', 'COMPLETED', 'ARCHIVED')),
  max_players integer NOT NULL DEFAULT 6 CHECK (max_players BETWEEN 1 AND 20),
  safety_notes text NOT NULL DEFAULT '',
  house_rules text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_tabletop_games_host ON tabletop.games(host_user_id, status);
CREATE INDEX idx_tabletop_games_world ON tabletop.games(world_id, status);

CREATE TABLE tabletop.game_members (
  game_id uuid NOT NULL REFERENCES tabletop.games(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
  character_id uuid REFERENCES tabletop.characters(id) ON DELETE SET NULL,
  membership_role text NOT NULL DEFAULT 'PLAYER'
    CHECK (membership_role IN ('PLAYER', 'CO_DM')),
  status text NOT NULL DEFAULT 'INVITED'
    CHECK (status IN ('INVITED', 'JOINED', 'READY', 'LEFT', 'REMOVED')),
  joined_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (game_id, user_id)
);
CREATE INDEX idx_tabletop_game_members_user ON tabletop.game_members(user_id, status);

CREATE TABLE tabletop.game_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id uuid NOT NULL REFERENCES tabletop.games(id) ON DELETE CASCADE,
  title text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 160),
  scheduled_for timestamptz,
  status text NOT NULL DEFAULT 'SCHEDULED'
    CHECK (status IN ('SCHEDULED', 'LIVE', 'PAUSED', 'COMPLETED', 'CANCELLED')),
  public_notes text NOT NULL DEFAULT '',
  dm_notes text NOT NULL DEFAULT '',
  started_at timestamptz,
  ended_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ended_at IS NULL OR started_at IS NOT NULL),
  CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX idx_tabletop_game_sessions_game ON tabletop.game_sessions(game_id, created_at DESC);

GRANT USAGE ON SCHEMA identity, tabletop TO tabletop_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  identity.users, identity.user_profiles, identity.global_roles, identity.world_roles,
  identity.sessions, tabletop.characters, tabletop.games, tabletop.game_members,
  tabletop.game_sessions TO tabletop_app;
GRANT SELECT, INSERT ON identity.audit_log TO tabletop_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA identity, tabletop TO tabletop_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA identity, tabletop REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA identity, tabletop GRANT SELECT ON TABLES TO tabletop_app;
