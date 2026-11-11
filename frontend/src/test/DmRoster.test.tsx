import { render, screen, waitFor } from "@testing-library/react";
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
});
