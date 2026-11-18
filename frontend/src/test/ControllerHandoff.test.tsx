import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ControlPanel from "../features/game-console/ControlPanel";
import * as api from "../features/game-console/api";

vi.mock("../features/game-console/api", () => ({
  loadController: vi.fn(), handoffController: vi.fn(), renewControllerPresence: vi.fn(), loadCharacterRecap: vi.fn(),
}));
const scope = { world: "world", branch: "branch", run: "run", entity: "body" };
beforeEach(() => {
  vi.mocked(api.loadController).mockReset().mockResolvedValue({ control: null, disconnect_policy: "EXPLICIT_HANDOFF" });
  vi.mocked(api.handoffController).mockReset();
  vi.mocked(api.renewControllerPresence).mockReset();
  vi.mocked(api.loadCharacterRecap).mockReset();
});

describe("explicit character control", () => {
  it("keeps human control on failure and retries the same uncertain handoff key", async () => {
    vi.mocked(api.handoffController).mockRejectedValue(new Error("Network unavailable"));
    const user = userEvent.setup(); const mode = vi.fn();
    render(<ControlPanel scope={scope} onModeChange={mode} onProgress={vi.fn()} />);
    await screen.findByText("You are playing");
    await user.click(screen.getByRole("button", { name: "Let character act" }));
    await screen.findByRole("alert");
    expect(mode).toHaveBeenLastCalledWith("HUMAN", undefined);
    const first = vi.mocked(api.handoffController).mock.calls[0];
    await user.click(screen.getByRole("button", { name: "Reload control" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Let character act" }));
    expect(vi.mocked(api.handoffController).mock.calls[1]).toEqual(first);
  });

  it("reads confirmed state after handoff and preserves a valid action limit", async () => {
    const automatic: api.ControllerState = { epoch: 1, mode: "AUTONOMOUS", step: 0, max_steps: 3, last_error: null, next_due: "2040-01-01T00:00:00Z" };
    vi.mocked(api.handoffController).mockImplementation(async () => {
      vi.mocked(api.loadController).mockResolvedValue({ control: automatic, disconnect_policy: "EXPLICIT_HANDOFF" });
      return { state: automatic };
    });
    const user = userEvent.setup();
    render(<ControlPanel scope={scope} onModeChange={vi.fn()} onProgress={vi.fn()} />);
    await screen.findByText("You are playing");
    const limit = screen.getByLabelText("Autonomous action limit");
    await user.clear(limit);
    expect(screen.getByRole("button", { name: "Let character act" })).toBeDisabled();
    await user.type(limit, "3");
    await user.click(screen.getByRole("button", { name: "Let character act" }));
    await screen.findByText("Character is acting");
    expect(screen.getByRole("button", { name: "Let character act" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Take control" })).toBeEnabled();
    expect(api.handoffController).toHaveBeenCalledWith(scope, "AUTONOMOUS", 0, 3, expect.any(String), undefined);
  });

  it("starts presence renewal only after opting into a disconnect timeout", async () => {
    const human: api.ControllerState = {
      epoch: 1, mode: "HUMAN", step: 0, max_steps: 20, last_error: null,
      next_due: "2040-01-01T00:00:00Z", disconnect_after_seconds: 15,
    };
    vi.mocked(api.handoffController).mockImplementation(async () => {
      vi.mocked(api.loadController).mockResolvedValue({
        control: human, disconnect_policy: "AUTOPLAY_ON_DISCONNECT",
      });
      return { state: human };
    });
    vi.mocked(api.renewControllerPresence).mockResolvedValue({ state: human });
    const user = userEvent.setup();
    render(<ControlPanel scope={scope} onModeChange={vi.fn()} onProgress={vi.fn()} />);
    await screen.findByText("You are playing");
    const setting = screen.getByLabelText("On disconnect");
    expect(setting).toHaveValue("0");
    expect(api.renewControllerPresence).not.toHaveBeenCalled();
    await user.selectOptions(setting, "15");
    await waitFor(() => expect(api.renewControllerPresence).toHaveBeenCalledWith(scope, 1, expect.any(AbortSignal)));
    expect(setting).toHaveValue("15");
    expect(api.handoffController).toHaveBeenCalledWith(scope, "HUMAN", 0, 20, expect.any(String), 15);
  });

  it("ignores an obsolete controller read after changing characters", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof api.loadController>>) => void;
    vi.mocked(api.loadController).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const mode = vi.fn(); const progress = vi.fn();
    const view = render(<ControlPanel scope={scope} onModeChange={mode} onProgress={progress} />);
    view.rerender(<ControlPanel scope={{ ...scope, entity: "other" }} onModeChange={mode} onProgress={progress} />);
    await screen.findByText("You are playing");
    await act(async () => resolve({ control: { epoch: 8, mode: "AUTONOMOUS", step: 9, max_steps: 10, next_due: "", last_error: null }, disconnect_policy: "EXPLICIT_HANDOFF" }));
    expect(mode).toHaveBeenLastCalledWith("HUMAN", undefined);
    expect(screen.queryByText("Character is acting")).not.toBeInTheDocument();
  });

  it("shows the scoped recap and clears it when changing characters", async () => {
    vi.mocked(api.loadController).mockResolvedValue({
      disconnect_policy: "EXPLICIT_HANDOFF",
      control: { epoch: 3, mode: "HUMAN", step: 0, max_steps: 10, next_due: "", last_error: null },
    });
    vi.mocked(api.loadCharacterRecap).mockResolvedValue({
      available: true, entries: [{ narration_id: "line", text: "You hear the bell." }],
    });
    const user = userEvent.setup(); const mode = vi.fn(); const progress = vi.fn();
    const view = render(<ControlPanel scope={scope} onModeChange={mode} onProgress={progress} />);
    await user.click(await screen.findByRole("button", { name: "Show character recap" }));
    expect(await screen.findByRole("region", { name: "Character recap" })).toHaveTextContent("You hear the bell.");
    expect(api.loadCharacterRecap).toHaveBeenCalledWith(scope, expect.any(AbortSignal));
    view.rerender(<ControlPanel scope={{ ...scope, entity: "other" }} onModeChange={mode} onProgress={progress} />);
    expect(screen.queryByRole("region", { name: "Character recap" })).not.toBeInTheDocument();
  });
});
