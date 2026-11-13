import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RosterEditor } from "../features/dm/DungeonMasterPage";
import * as api from "../features/dm/api";
import type { CurrentUser } from "../features/auth/types";
import type { HostedGame } from "../features/player/api";

vi.mock("../features/dm/api", () => ({ assignableCharacters: vi.fn(), setMember: vi.fn() }));
const player: CurrentUser = {
  user_id: "player", actor_id: "actor", username: "mira",
  profile: { display_name: "Mira", timezone: "UTC", locale: "en-US" },
  global_roles: [], world_roles: [{ world_id: "world", roles: ["PLAYER", "DM"] }],
  password_change_required: false, is_active: true, is_admin: false,
  has_dm_role: true, has_player_role: true, created_at: "2026-11-10T00:00:00Z",
};
const game: HostedGame = {
  game_id: "game", world_id: "world", host_user_id: "host", name: "Campaign",
  description: "", status: "DRAFT", max_players: 6, safety_notes: "", house_rules: "", members: [],
};
const character = { character_id: "body", name: "Nyra", class_name: "Ranger", level: 1, status: "ALIVE" };
const operation = async (work: () => Promise<unknown>) => { await work(); };
const secondPlayer: CurrentUser = { ...player, user_id: "second", username: "tal",
  profile: { ...player.profile, display_name: "Tal" } };
const secondCharacter = { ...character, character_id: "second-body", name: "Tarin" };
function pendingCharacters() {
  let resolve!: (rows: api.AssignableCharacter[]) => void;
  const promise = new Promise<api.AssignableCharacter[]>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("DM roster character assignment", () => {
  it("sends the selected character and lets a dual-role account play or co-DM explicitly", async () => {
    vi.mocked(api.assignableCharacters).mockResolvedValue([character]);
    const user = userEvent.setup();
    render(<RosterEditor game={game} eligible={[player]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    await screen.findByRole("option", { name: /Nyra/ });
    expect(screen.getByLabelText("Membership role")).toHaveValue("PLAYER");
    await user.selectOptions(screen.getByLabelText("Playable character"), "body");
    await user.click(screen.getByRole("button", { name: "Invite" }));
    expect(api.setMember).toHaveBeenLastCalledWith("game", {
      user_id: "player", membership_role: "PLAYER", character_id: "body", status: "INVITED",
    });
    await user.selectOptions(screen.getByLabelText("Membership role"), "CO_DM");
    expect(screen.queryByLabelText("Playable character")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Invite" }));
    expect(api.setMember).toHaveBeenLastCalledWith("game", {
      user_id: "player", membership_role: "CO_DM", character_id: null, status: "INVITED",
    });
  });

  it("assigns an existing member without resetting their membership status", async () => {
    vi.mocked(api.assignableCharacters).mockResolvedValue([character]);
    const user = userEvent.setup();
    render(<RosterEditor game={{ ...game, members: [{ user_id: "player", username: "mira",
      display_name: "Mira", membership_role: "PLAYER", status: "READY" }] }}
      eligible={[player]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    await screen.findByRole("option", { name: /Nyra/ });
    await user.selectOptions(screen.getByLabelText("Playable character"), "body");
    await user.click(screen.getByRole("button", { name: "Update member" }));
    expect(api.setMember).toHaveBeenLastCalledWith("game", expect.objectContaining({ character_id: "body", status: "READY" }));
  });

  it("blocks writes on lookup errors and supports retry", async () => {
    vi.mocked(api.assignableCharacters).mockRejectedValueOnce(new Error("Permission denied"))
      .mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<RosterEditor game={game} eligible={[player]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    expect(await screen.findByRole("alert")).toHaveTextContent("Permission denied");
    expect(screen.getByRole("button", { name: "Invite" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Retry characters" }));
    await waitFor(() => expect(screen.getByText(/No characters available/)).toBeVisible());
  });

  it("clears the previous player's choices and blocks save while a new lookup is pending", async () => {
    const pending = pendingCharacters();
    vi.mocked(api.assignableCharacters).mockReset().mockResolvedValueOnce([character])
      .mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<RosterEditor game={game} eligible={[player, secondPlayer]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    await screen.findByRole("option", { name: /Nyra/ });
    await user.selectOptions(screen.getByLabelText("Eligible user"), "second");
    expect(screen.queryByRole("option", { name: /Nyra/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Playable character")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Invite" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Loading characters");
    await act(async () => pending.resolve([secondCharacter]));
    await screen.findByRole("option", { name: /Tarin/ });
    expect(screen.getByRole("button", { name: "Invite" })).toBeEnabled();
  });

  it("ignores an obsolete response after the selected player's response completes", async () => {
    const first = pendingCharacters(), second = pendingCharacters();
    vi.mocked(api.assignableCharacters).mockReset().mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const user = userEvent.setup();
    render(<RosterEditor game={game} eligible={[player, secondPlayer]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    await user.selectOptions(screen.getByLabelText("Eligible user"), "second");
    await act(async () => second.resolve([secondCharacter]));
    await screen.findByRole("option", { name: /Tarin/ });
    await act(async () => first.resolve([character]));
    expect(screen.queryByRole("option", { name: /Nyra/ })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Playable character"), "second-body");
    await user.click(screen.getByRole("button", { name: "Invite" }));
    expect(api.setMember).toHaveBeenLastCalledWith("game", expect.objectContaining({
      user_id: "second", character_id: "second-body",
    }));
  });

  it("disables save when returning from co-DM to a pending player lookup", async () => {
    const pending = pendingCharacters();
    vi.mocked(api.assignableCharacters).mockReset().mockResolvedValueOnce([character])
      .mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<RosterEditor game={game} eligible={[player]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    await screen.findByRole("option", { name: /Nyra/ });
    await user.selectOptions(screen.getByLabelText("Membership role"), "CO_DM");
    await user.selectOptions(screen.getByLabelText("Membership role"), "PLAYER");
    expect(screen.getByRole("button", { name: "Invite" })).toBeDisabled();
    await act(async () => pending.resolve([character]));
    await screen.findByRole("option", { name: /Nyra/ });
  });

  it("clears a previous player's lookup error when a different player is selected", async () => {
    const pending = pendingCharacters();
    vi.mocked(api.assignableCharacters).mockReset().mockRejectedValueOnce(new Error("Old player error"))
      .mockReturnValueOnce(pending.promise);
    const user = userEvent.setup();
    render(<RosterEditor game={game} eligible={[player, secondPlayer]} onOperation={operation} />);
    await user.selectOptions(screen.getByLabelText("Eligible user"), "player");
    expect(await screen.findByRole("alert")).toHaveTextContent("Old player error");
    await user.selectOptions(screen.getByLabelText("Eligible user"), "second");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading characters");
    await act(async () => pending.resolve([secondCharacter]));
    await screen.findByRole("option", { name: /Tarin/ });
  });
});
