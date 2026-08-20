import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

const baseUser = {
  user_id: "10000000-0000-4000-8000-000000000001",
  actor_id: "20000000-0000-4000-8000-000000000001",
  username: "admin",
  profile: { display_name: "Administrator", timezone: "UTC", locale: "en-US" },
  global_roles: ["ADMIN"], world_roles: [], is_active: true, is_admin: true,
  has_dm_role: true, has_player_role: true, last_login_at: null,
  created_at: "2026-08-20T00:00:00Z",
};

describe("account bootstrap", () => {
  it("signs in with the first-start account and requires a private password", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const path = String(input);
      if (path.endsWith("/auth/session")) return json({ error: "authentication_required" }, 401);
      if (path.endsWith("/auth/login")) {
        expect(JSON.parse(String(init?.body))).toEqual({ username: "admin", password: "admin123" });
        return json({ user: { ...baseUser, password_change_required: true } });
      }
      if (path.endsWith("/auth/change-password")) return json({ user: { ...baseUser, password_change_required: false } });
      return json({ error: "endpoint_unavailable" }, 404);
    });

    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    await user.type(screen.getByLabelText("Password"), "admin123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Protect the administrator account" })).toBeVisible();
    await user.type(screen.getByLabelText("Current password"), "admin123");
    await user.type(screen.getByLabelText("New password"), "Private-Admin-2026!");
    await user.type(screen.getByLabelText("Confirm new password"), "Private-Admin-2026!");
    await user.click(screen.getByRole("button", { name: "Change password and continue" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(screen.queryByText(/operator token/i)).not.toBeInTheDocument();
  });
});
