import { apiRequest } from "../../core/api/client";
import type { CurrentUser, UserProfile } from "./types";

type UserEnvelope = { user: CurrentUser };

export async function loadSession(): Promise<CurrentUser> {
  return (await apiRequest<UserEnvelope>("/auth/session")).user;
}

export async function login(username: string, password: string): Promise<CurrentUser> {
  return (
    await apiRequest<UserEnvelope>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    })
  ).user;
}

export async function logout(): Promise<void> {
  await apiRequest<void>("/auth/logout", { method: "POST" });
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<CurrentUser> {
  return (
    await apiRequest<UserEnvelope>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    })
  ).user;
}

export async function updateProfile(profile: UserProfile): Promise<CurrentUser> {
  return (
    await apiRequest<UserEnvelope>("/profile", {
      method: "PUT",
      body: JSON.stringify(profile),
    })
  ).user;
}
