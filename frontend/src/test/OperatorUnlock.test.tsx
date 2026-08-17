import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";

const OPERATOR_TOKEN = "fresh-session-token";

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("operator unlock", () => {
  it("keeps token entry reachable after bootstrap 401 and reloads live settings", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const token = new Headers(init?.headers).get("X-TTDM-Operator-Token");
      if (token !== OPERATOR_TOKEN) return json({ error: "operator_authorization_required" }, 401);

      const path = String(input);
      if (path.endsWith("/meta")) {
        return json({
          contract_version: "2.0.0",
          kernel: "tabletop-simulation-kernel",
          persona_schema_version: "2.0.0",
          persona_dimensions: 80,
          telemetry_enabled: false,
          migrations_from_v1_supported: false,
        });
      }
      if (path.endsWith("/worlds")) {
        return json([{
          world_id: "11111111-1111-4111-8111-111111111111",
          name: "Unlocked world",
          status: "ACTIVE",
        }]);
      }
      if (path.endsWith("/telemetry")) {
        return json({ human_telemetry_enabled: false, local_only: true });
      }
      return json({ error: "not_found" }, 404);
    });

    const user = userEvent.setup();
    render(<MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(await screen.findByText("operator_authorization_required")).toBeVisible();
    const tokenInput = screen.getByLabelText("Operator token");
    await user.type(tokenInput, OPERATOR_TOKEN);
    await user.click(screen.getByRole("button", { name: "Save and verify" }));

    expect(await screen.findByText("Operator access verified for this browser session.")).toBeVisible();
    expect(sessionStorage.getItem("ttdm.v2.operator-token")).toBe(OPERATOR_TOKEN);
    await waitFor(() => expect(screen.getByText("tabletop-simulation-kernel")).toBeVisible());
    expect(screen.getByRole("combobox", { name: "Active world" })).toHaveDisplayValue(
      "Unlocked world",
    );
  });
});
