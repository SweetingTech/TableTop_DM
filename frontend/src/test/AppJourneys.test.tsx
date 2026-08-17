import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "../App";

function renderRoute(route: string) {
  return render(<MemoryRouter initialEntries={[route]}><App /></MemoryRouter>);
}

describe("simulation kernel application journeys", () => {
  it("renders URL-addressable navigation and the settings safety defaults", async () => {
    renderRoute("/settings");
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(screen.getByTestId("app-shell")).toBeVisible();
    expect(screen.getByRole("link", { name: "Game Console" })).toHaveAttribute("href", "/game");
    expect(screen.getByRole("checkbox", { name: "Human telemetry" })).not.toBeChecked();
    expect((await screen.findAllByTestId("demo-mode-banner")).length).toBeGreaterThan(0);
  });

  it("creates a clearly demo-labeled world when the live endpoint is unavailable", async () => {
    const user = userEvent.setup();
    renderRoute("/control");
    expect(await screen.findByRole("heading", { name: "Control Plane" })).toBeVisible();
    await user.type(screen.getByTestId("world-name"), "Ashfall Reach");
    await user.click(screen.getByRole("button", { name: "Create world" }));
    expect(await within(screen.getByTestId("world-list")).findByText("Ashfall Reach")).toBeVisible();
  });

  it("generates and validates a seeded persona", async () => {
    const user = userEvent.setup();
    renderRoute("/personas");
    expect(await screen.findByRole("heading", { name: "Persona Studio" })).toBeVisible();
    const seed = screen.getByTestId("persona-seed");
    await user.clear(seed);
    await user.type(seed, "404");
    await user.click(screen.getByRole("button", { name: "Generate persona" }));
    expect(await screen.findByText("Dependency graph and values are valid.")).toBeVisible();
    expect(screen.getByTestId("persona-validation")).toHaveTextContent("404");
  });

  it("launches the deterministic fallback scenario and exposes normalized results", async () => {
    const user = userEvent.setup();
    renderRoute("/scenarios");
    expect(await screen.findByRole("heading", { name: "Scenario Lab" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Run scenario" }));
    const results = await screen.findByTestId("scenario-results");
    expect(results).toBeVisible();
    expect(screen.getByText("Canonical world unchanged")).toBeVisible();
    const rows = within(results).getAllByRole("row");
    rows[2].focus();
    await user.keyboard("{Enter}");
    expect(rows[2]).toHaveAttribute("aria-selected", "true");
  });

  it("reviews a calibration proposal before promoting its policy", async () => {
    const user = userEvent.setup();
    renderRoute("/calibration");
    expect(await screen.findByRole("heading", { name: "Calibration" })).toBeVisible();
    const promote = screen.getByRole("button", { name: "Promote policy" });
    expect(promote).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Approve proposal" }));
    expect(await screen.findByRole("button", { name: "Proposal reviewed" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Promote policy" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Promote policy" }));
    expect(await screen.findByRole("button", { name: "Policy promoted" })).toBeDisabled();
  });
});
