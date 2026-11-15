import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../core/api/client";
import * as api from "../features/player/api";
import { CharacterStatePanel } from "../features/player/CharacterStatePanel";

const card: api.CharacterRecord = {
  character_id: "a", owner_user_id: "owner", world_id: "world", entity_id: "body",
  name: "Card", species: "Human", class_name: "Adventurer", background: "Sailor", level: 1,
  status: "ALIVE", current_hit_points: 10, maximum_hit_points: 10, armor_class: 10, speed: 30,
  ability_scores: {}, sheet: {}, authored_identity: { backstory: "", motives: [], values: [], bonds: [], secrets: [], initial_known_facts: [] },
  card_version: "version", creation_method: "BUILT", updated_at: "now",
};
const live = (id = "a"): api.CharacterState => ({
  character_id: id, card_version: "version", source: "KERNEL",
  body: { world_id: "world", branch_id: "branch", entity_id: "body", projection_version: 5,
    status: "INCAPACITATED", hp: 3, max_hp: 12, armor: 17, speed: 20, mana: 2,
    equipped_weapon: "SPEAR", inventory: { SPEAR: 1 }, known_spells: ["MEND"], conditions: ["stunned"] },
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("canonical character resources", () => {
  it("shows live effects/equipment and never presents bound card controls", async () => {
    vi.spyOn(api, "getCharacterState").mockResolvedValue(live());
    render(<CharacterStatePanel character={card} onUpdate={vi.fn()} />);
    expect(await screen.findByLabelText("Character hit points")).toHaveTextContent("3/12");
    expect(screen.queryByRole("button", { name: "Save status" })).not.toBeInTheDocument();
    expect(screen.getByText("INCAPACITATED")).toBeVisible();
    expect(screen.getByText("SPEAR", { selector: "strong" })).toBeVisible();
    expect(screen.getByLabelText("Inventory")).toHaveTextContent("SPEAR: 1");
    expect(screen.queryByText("10/10")).not.toBeInTheDocument();
  });

  it("clears live values on authorization loss and keeps refresh focus", async () => {
    const get = vi.spyOn(api, "getCharacterState").mockResolvedValueOnce(live())
      .mockRejectedValueOnce(new ApiError("permission_denied", 403));
    const user = userEvent.setup();
    render(<CharacterStatePanel character={card} onUpdate={vi.fn()} />);
    await screen.findByLabelText("Character hit points");
    const refresh = screen.getByRole("button", { name: "Refresh character state" });
    await user.click(refresh);
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer have access");
    expect(screen.queryByLabelText("Character hit points")).not.toBeInTheDocument();
    expect(screen.queryByText("10/10")).not.toBeInTheDocument();
    expect(refresh).toHaveFocus();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("cancels the old scope and ignores late responses after changing characters", async () => {
    let resolveOld!: (value: api.CharacterState) => void;
    let firstSignal: AbortSignal | undefined;
    vi.spyOn(api, "getCharacterState").mockImplementationOnce((_id, signal) => {
      firstSignal = signal; return new Promise((resolve) => { resolveOld = resolve; });
    }).mockResolvedValueOnce({ ...live("b"), body: { ...live("b").body!, hp: 7 } });
    const { rerender } = render(<CharacterStatePanel character={card} onUpdate={vi.fn()} />);
    rerender(<CharacterStatePanel character={{ ...card, character_id: "b" }} onUpdate={vi.fn()} />);
    expect(await screen.findByLabelText("Character hit points")).toHaveTextContent("7/12");
    await act(async () => resolveOld(live()));
    expect(firstSignal?.aborted).toBe(true);
    expect(screen.getByLabelText("Character hit points")).toHaveTextContent("7/12");
  });

  it("allows authored starting values only after the server confirms an unbound card", async () => {
    vi.spyOn(api, "getCharacterState").mockResolvedValue({ character_id: "a", card_version: "v", source: "AUTHORED", body: null });
    const save = vi.fn().mockResolvedValue(undefined);
    render(<CharacterStatePanel character={{ ...card, entity_id: null }} onUpdate={save} />);
    const hp = await screen.findByLabelText("Current hit points");
    fireEvent.change(hp, { target: { value: "4" } });
    await userEvent.click(screen.getByRole("button", { name: "Save status" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ status: "ALIVE", current_hit_points: 4 }));
  });

  it("does not start a second live request while a visibility-triggered read is in flight", async () => {
    let resolve!: (value: api.CharacterState) => void;
    const get = vi.spyOn(api, "getCharacterState").mockImplementation(() => new Promise((r) => { resolve = r; }));
    render(<CharacterStatePanel character={card} onUpdate={vi.fn()} />);
    fireEvent(document, new Event("visibilitychange"));
    fireEvent(document, new Event("visibilitychange"));
    expect(get).toHaveBeenCalledTimes(1);
    await act(async () => resolve(live()));
  });

  it("rejects a malformed bound response instead of falling back to authored health", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => ({ character_id: "a", source: "KERNEL" }) }));
    await expect(api.getCharacterState("a")).rejects.toThrow("Invalid character state");
  });
});
