import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CharacterIdentityFields } from "../features/player/CharacterIdentityFields";
import { identityDraft, identityPayload } from "../features/player/characterIdentity";

function Form() {
  const [draft, setDraft] = useState(identityDraft);
  return <><CharacterIdentityFields value={draft} onChange={setDraft} />
    <output aria-label="Serialized identity">{JSON.stringify(identityPayload(draft))}</output></>;
}

describe("authored character identity", () => {
  it("keeps newlines editable and serializes separate trimmed claims", async () => {
    const user = userEvent.setup();
    render(<Form />);
    await user.type(screen.getByLabelText("Backstory"), "Raised by sailors.");
    await user.type(screen.getByLabelText("Motives"), "Find my sister.{enter}Protect the crew.");
    await user.type(screen.getByLabelText("Character secrets"), "I hid the map.");
    const payload = JSON.parse(screen.getByLabelText("Serialized identity").textContent!);
    expect(payload.backstory).toBe("Raised by sailors.");
    expect(payload.motives).toEqual(["Find my sister.", "Protect the crew."]);
    expect(payload.secrets).toEqual(["I hid the map."]);
    expect(screen.getByLabelText("Backstory")).toHaveAttribute("maxlength", "12000");
  });

  it("round-trips the complete authored identity without folding knowledge into backstory", () => {
    const identity = { backstory: "Harbor orphan.", motives: ["Find family"], values: ["Mercy"],
      bonds: ["The crew"], secrets: ["Stolen map"], initial_known_facts: ["The ferry sails at dawn."] };
    expect(identityPayload(identityDraft(identity))).toEqual(identity);
    expect(identityPayload(identityDraft()).initial_known_facts).toEqual([]);
  });
});
