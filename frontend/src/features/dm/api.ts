import { apiRequest, unpackItems } from "../../core/api/client";
import type { CurrentUser } from "../auth/types";
import type { HostedGame } from "../player/api";

export type HostedSession = {
  session_id: string;
  game_id: string;
  title: string;
  scheduled_for?: string | null;
  status: string;
  public_notes: string;
  dm_notes?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
};

export async function listGames(): Promise<HostedGame[]> {
  return unpackItems(await apiRequest<HostedGame[] | { items?: HostedGame[] }>("/games"));
}

export async function createGame(input: Record<string, unknown>): Promise<HostedGame> {
  return apiRequest<HostedGame>("/dm/games", { method: "POST", body: JSON.stringify(input) });
}

export async function updateGame(gameId: string, input: Record<string, unknown>): Promise<HostedGame> {
  return apiRequest<HostedGame>(`/dm/games/${gameId}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function eligibleUsers(worldId: string): Promise<CurrentUser[]> {
  return unpackItems(await apiRequest<CurrentUser[] | { items?: CurrentUser[] }>(`/dm/worlds/${worldId}/eligible-users`));
}

export async function setMember(gameId: string, input: Record<string, unknown>): Promise<HostedGame> {
  return apiRequest<HostedGame>(`/dm/games/${gameId}/members`, { method: "PUT", body: JSON.stringify(input) });
}

export async function removeMember(gameId: string, userId: string): Promise<void> {
  await apiRequest<void>(`/dm/games/${gameId}/members/${userId}`, { method: "DELETE" });
}

export async function listSessions(gameId: string): Promise<HostedSession[]> {
  return unpackItems(await apiRequest<HostedSession[] | { items?: HostedSession[] }>(`/games/${gameId}/sessions`));
}

export async function createSession(gameId: string, input: Record<string, unknown>): Promise<HostedSession> {
  return apiRequest<HostedSession>(`/dm/games/${gameId}/sessions`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateSession(gameId: string, sessionId: string, input: Record<string, unknown>): Promise<HostedSession> {
  return apiRequest<HostedSession>(`/dm/games/${gameId}/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify(input) });
}
