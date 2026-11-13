import type { CharacterIdentity } from "./api";

export type IdentityDraft = { [K in keyof CharacterIdentity]: string };

export function identityDraft(identity?: CharacterIdentity): IdentityDraft {
  return {
    backstory: identity?.backstory ?? "", motives: identity?.motives.join("\n") ?? "",
    values: identity?.values.join("\n") ?? "", bonds: identity?.bonds.join("\n") ?? "",
    secrets: identity?.secrets.join("\n") ?? "",
    initial_known_facts: identity?.initial_known_facts.join("\n") ?? "",
  };
}

export function identityPayload(draft: IdentityDraft): CharacterIdentity {
  const lines = (text: string) => text.split("\n").map((line) => line.trim()).filter(Boolean);
  return {
    backstory: draft.backstory.trim(), motives: lines(draft.motives), values: lines(draft.values),
    bonds: lines(draft.bonds), secrets: lines(draft.secrets),
    initial_known_facts: lines(draft.initial_known_facts),
  };
}
