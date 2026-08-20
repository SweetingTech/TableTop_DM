import { apiRequest, unpackItems } from "../../core/api/client";

export type CharacterRecord = {
  character_id: string;
  owner_user_id: string;
  world_id?: string | null;
  name: string;
  species: string;
  class_name: string;
  background: string;
  level: number;
  status: "ALIVE" | "DEAD" | "MISSING" | "RETIRED";
  current_hit_points: number;
  maximum_hit_points: number;
  armor_class: number;
  speed: number;
  ability_scores: Record<string, number>;
  sheet: Record<string, unknown>;
  creation_method: "BUILT" | "GENERATED" | "IMPORTED";
  source_filename?: string | null;
  updated_at: string;
};

export type GameMember = {
  user_id: string;
  username: string;
  display_name: string;
  character_id?: string | null;
  character_name?: string | null;
  membership_role: string;
  status: string;
};

export type HostedGame = {
  game_id: string;
  world_id: string;
  host_user_id: string;
  name: string;
  description: string;
  status: string;
  max_players: number;
  safety_notes: string;
  house_rules: string;
  members: GameMember[];
};

export async function listCharacters(): Promise<CharacterRecord[]> {
  return unpackItems(await apiRequest<CharacterRecord[] | { items?: CharacterRecord[] }>("/player/characters"));
}

export async function createCharacter(input: Record<string, unknown>): Promise<CharacterRecord> {
  return apiRequest<CharacterRecord>("/player/characters", { method: "POST", body: JSON.stringify(input) });
}

export async function updateCharacter(characterId: string, input: Record<string, unknown>): Promise<CharacterRecord> {
  return apiRequest<CharacterRecord>(`/player/characters/${characterId}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function deleteCharacter(characterId: string): Promise<void> {
  await apiRequest<void>(`/player/characters/${characterId}`, { method: "DELETE" });
}

export async function listGames(): Promise<HostedGame[]> {
  return unpackItems(await apiRequest<HostedGame[] | { items?: HostedGame[] }>("/games"));
}
