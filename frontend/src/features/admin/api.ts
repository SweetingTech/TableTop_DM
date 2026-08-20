import { apiRequest, unpackItems } from "../../core/api/client";
import type { CurrentUser, UserProfile } from "../auth/types";

export async function listUsers(): Promise<CurrentUser[]> {
  return unpackItems(await apiRequest<CurrentUser[] | { items?: CurrentUser[] }>("/admin/users"));
}

export async function createUser(input: {
  username: string;
  temporary_password: string;
  profile: UserProfile;
}): Promise<CurrentUser> {
  return (
    await apiRequest<{ user: CurrentUser }>("/admin/users", {
      method: "POST",
      body: JSON.stringify(input),
    })
  ).user;
}

export async function updateUser(
  userId: string,
  input: { username?: string; is_active?: boolean; profile?: UserProfile },
): Promise<CurrentUser> {
  return (
    await apiRequest<{ user: CurrentUser }>(`/admin/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    })
  ).user;
}

export async function setGlobalRoles(userId: string, roles: string[]): Promise<CurrentUser> {
  return (
    await apiRequest<{ user: CurrentUser }>(`/admin/users/${userId}/roles`, {
      method: "PUT",
      body: JSON.stringify({ roles }),
    })
  ).user;
}

export async function setWorldRoles(
  userId: string,
  worldId: string,
  roles: string[],
): Promise<CurrentUser> {
  return (
    await apiRequest<{ user: CurrentUser }>(`/admin/users/${userId}/worlds/${worldId}/roles`, {
      method: "PUT",
      body: JSON.stringify({ roles }),
    })
  ).user;
}

export async function resetPassword(userId: string, temporaryPassword: string): Promise<void> {
  await apiRequest<void>(`/admin/users/${userId}/password`, {
    method: "PUT",
    body: JSON.stringify({ temporary_password: temporaryPassword }),
  });
}

export async function deleteUser(userId: string): Promise<void> {
  await apiRequest<void>(`/admin/users/${userId}`, { method: "DELETE" });
}
