export type UserProfile = {
  display_name: string;
  legal_name?: string | null;
  email?: string | null;
  date_of_birth?: string | null;
  pronouns?: string | null;
  timezone: string;
  locale: string;
  bio?: string | null;
  avatar_uri?: string | null;
};

export type WorldRoleGrant = {
  world_id: string;
  roles: string[];
};

export type CurrentUser = {
  user_id: string;
  actor_id: string;
  username: string;
  profile: UserProfile;
  global_roles: string[];
  world_roles: WorldRoleGrant[];
  password_change_required: boolean;
  is_active: boolean;
  is_admin: boolean;
  has_dm_role: boolean;
  has_player_role: boolean;
  last_login_at?: string | null;
  created_at: string;
};
