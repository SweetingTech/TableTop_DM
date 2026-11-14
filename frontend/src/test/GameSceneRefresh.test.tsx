import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GameConsolePage from "../features/game-console/GameConsolePage";
import * as api from "../features/game-console/api";
import type { EventRecord, GameState, Sourced } from "../core/api/types";

const scope = vi.hoisted(() => ({ world: "world-a" }));
vi.mock("../app/AppContext", () => ({ useAppContext: () => ({ activeWorldId: scope.world }) }));
vi.mock("../features/game-console/api", () => ({ loadGameState: vi.fn(), proposeCommand: vi.fn(),
  loadController: vi.fn(async () => ({ control: null, disconnect_policy: "EXPLICIT_HANDOFF" })),
  handoffController: vi.fn() }));
const cursor = { world_id: "world-a", branch_id: "branch-a", observer_entity_id: "hero", event_id: "canonical-event", projection_version: 2 };
const experience: EventRecord = { event_id: "observation-1", source_event_id: "canonical-event", event_type: "tabletop.spatial.move", summary: "A footstep nearby.", created_at: "2026-11-13T00:00:00Z" };
const acknowledgement = { source: "live" as const, data: { event_id: "canonical-event", scene_refresh: cursor,
  event_type: "tabletop.spatial.move", summary: "RAW_CANONICAL_NOT_AN_OBSERVATION", created_at: experience.created_at } };
function game(version = 1, events: EventRecord[] = [], world = scope.world): Sourced<GameState> {
  return { source: "live", data: {
    run: { run_id: "run", world_id: world, name: "Live", kind: "LIVE", status: "RUNNING" },
    branch: { branch_id: "branch-a", world_id: world, name: "Canonical", kind: "CANONICAL", status: "ACTIVE" },
    entities: [{ entity_id: "hero", name: "Nyra", entity_type: "PLAYER_CHARACTER", location: `(${version - 1}, 0) · world` }],
    viewpoints: [{ entity_id: "hero", name: "Nyra", entity_type: "PLAYER_CHARACTER", can_act: true }, { entity_id: "second", name: "Tarin", entity_type: "PLAYER_CHARACTER", can_act: true }],
    observer_entity_id: "hero", events, projection_version: version, turn: 0, interaction_status: "ACTIVE",
  } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  scope.world = "world-a";
  vi.mocked(api.loadGameState).mockReset(); vi.mocked(api.proposeCommand).mockReset();
  vi.mocked(api.loadController).mockReset().mockResolvedValue({ control: null, disconnect_policy: "EXPLICIT_HANDOFF" });
});

describe("accepted action scene refresh", () => {
  it("catches controller progress that occurs while a scene reload unmounts the control panel", async () => {
    const pending = deferred<Sourced<GameState>>();
    const control = (step: number): Awaited<ReturnType<typeof api.loadController>> => ({
      control: { epoch: 1, mode: "PAUSED", step, max_steps: 2, last_error: "step_limit", next_due: "" },
      disconnect_policy: "EXPLICIT_HANDOFF",
    });
    vi.mocked(api.loadController).mockResolvedValueOnce(control(0)).mockResolvedValueOnce(control(1)).mockResolvedValue(control(2));
    vi.mocked(api.loadGameState).mockResolvedValueOnce(game()).mockResolvedValueOnce(game(2, [experience]))
      .mockImplementationOnce(() => pending.promise).mockResolvedValue(game(3, [experience, { ...experience, event_id: "observation-2", source_event_id: "event-2" }]));
    const user = userEvent.setup(); render(<GameConsolePage />);
    await screen.findByText("Autonomy paused");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.loadGameState).toHaveBeenCalledTimes(3));
    await act(async () => pending.resolve(game(2, [experience])));
    await screen.findByText("Projection 3");
    expect(screen.getByText("2 perceived events")).toBeInTheDocument();
    expect(api.loadGameState).toHaveBeenCalledTimes(4);
    expect(api.proposeCommand).not.toHaveBeenCalled();
  });

  it("reloads the scene automatically and never duplicates the persisted observation", async () => {
    vi.mocked(api.loadGameState).mockResolvedValueOnce(game()).mockResolvedValue(game(2, [experience]));
    vi.mocked(api.proposeCommand).mockResolvedValue(acknowledgement);
    const user = userEvent.setup(); render(<GameConsolePage />);
    await screen.findByText("Projection 1");
    await user.type(screen.getByLabelText("Command or dialogue"), "/move east");
    await user.click(screen.getByRole("button", { name: "Send proposal" }));
    await screen.findByText("Projection 2");
    expect(screen.getByLabelText("Command or dialogue")).toHaveFocus();
    expect(screen.getAllByText(experience.summary!)).toHaveLength(1);
    expect(screen.queryByText("RAW_CANONICAL_NOT_AN_OBSERVATION")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Projection 2");
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveFocus();
    expect(screen.getAllByText(experience.summary!)).toHaveLength(1);
    expect(api.proposeCommand).toHaveBeenCalledTimes(1);
  });

  it("shows accepted/pending status during lag and retries only scene reads after failure", async () => {
    const pending = deferred<Sourced<GameState>>();
    vi.mocked(api.loadGameState).mockResolvedValueOnce(game()).mockImplementationOnce(() => pending.promise).mockRejectedValueOnce(new Error("Scene unavailable")).mockResolvedValue(game(2, [experience]));
    vi.mocked(api.proposeCommand).mockResolvedValue(acknowledgement);
    const user = userEvent.setup(); render(<GameConsolePage />); await screen.findByText("Projection 1");
    await user.type(screen.getByLabelText("Command or dialogue"), "/move east");
    await user.click(screen.getByRole("button", { name: "Send proposal" }));
    await screen.findByText(/Action accepted.*updating/i);
    expect(screen.queryByText("RAW_CANONICAL_NOT_AN_OBSERVATION")).not.toBeInTheDocument();
    await act(async () => pending.resolve(game(2, [experience])));
    await screen.findByText("Projection 2");
    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText(/Action was accepted.*Scene unavailable/i);
    await user.click(screen.getByRole("button", { name: /Retry/i }));
    await screen.findByText("Projection 2"); expect(api.proposeCommand).toHaveBeenCalledTimes(1);
  });

  it("deduplicates multiple observation IDs for one source event", async () => {
    vi.mocked(api.loadGameState).mockResolvedValue(game(2, [experience, { ...experience, event_id: "observation-2" }]));
    render(<GameConsolePage />); await screen.findByText("Projection 2");
    expect(screen.getAllByText(experience.summary!)).toHaveLength(1);
    expect(screen.getByText("1 perceived events")).toBeInTheDocument();
  });

  it("clears drafts and ignores old command completion after a world switch", async () => {
    const pending = deferred<typeof acknowledgement>();
    vi.mocked(api.loadGameState).mockImplementation(async (world) => game(1, [], world));
    vi.mocked(api.proposeCommand).mockImplementation(() => pending.promise);
    const user = userEvent.setup(); const view = render(<GameConsolePage />); await screen.findByText("Projection 1");
    await user.type(screen.getByLabelText("Command or dialogue"), "Old world private dialogue");
    await user.click(screen.getByRole("button", { name: "Send proposal" }));
    scope.world = "world-b"; view.rerender(<GameConsolePage />);
    await waitFor(() => expect(screen.getByLabelText("Command or dialogue")).toHaveValue(""));
    await act(async () => pending.resolve(acknowledgement));
    expect(screen.queryByText("RAW_CANONICAL_NOT_AN_OBSERVATION")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Command or dialogue")).toHaveValue("");
  });

  it("clears a private draft when selecting another embodied viewpoint", async () => {
    vi.mocked(api.loadGameState).mockResolvedValue(game());
    const user = userEvent.setup(); render(<GameConsolePage />); await screen.findByText("Projection 1");
    await user.type(screen.getByLabelText("Command or dialogue"), "Nyra's private draft");
    await user.selectOptions(screen.getByLabelText("Embodied viewpoint"), "second");
    await waitFor(() => expect(screen.getByLabelText("Command or dialogue")).toHaveValue(""));
  });
});
