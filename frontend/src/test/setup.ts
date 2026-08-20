import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    if (String(input).endsWith("/auth/session")) {
      return new Response(JSON.stringify({ user: {
        user_id: "10000000-0000-4000-8000-000000000001",
        actor_id: "20000000-0000-4000-8000-000000000001",
        username: "admin",
        profile: { display_name: "Administrator", timezone: "UTC", locale: "en-US" },
        global_roles: ["ADMIN"], world_roles: [], password_change_required: false,
        is_active: true, is_admin: true, has_dm_role: true, has_player_role: true,
        last_login_at: null, created_at: "2026-08-20T00:00:00Z",
      } }), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ error: "endpoint_unavailable" }), { status: 404, headers: { "Content-Type": "application/json" } });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
