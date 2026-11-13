import { useId } from "react";
import type { IdentityDraft } from "./characterIdentity";

const listFields = ["motives", "values", "bonds", "secrets", "initial_known_facts"] as const;
const labels = {
  motives: "Motives", values: "Values", bonds: "Bonds", secrets: "Character secrets",
  initial_known_facts: "Starting knowledge claims",
};
export function CharacterIdentityFields({ value, onChange }: {
  value: IdentityDraft;
  onChange: (draft: IdentityDraft) => void;
}) {
  const fieldId = useId();
  return <fieldset className="character-identity-fields">
    <legend>Character identity</legend>
    <p>Describe the character's own life and outlook. Keep private DM plans out of this card.</p>
    <label htmlFor={`${fieldId}-backstory`}>Backstory</label>
    <textarea id={`${fieldId}-backstory`} value={value.backstory} maxLength={12000} rows={5}
      onChange={(event) => onChange({ ...value, backstory: event.target.value })} />
    <p>Use one entry per line, up to 20 entries of 500 characters in each field.</p>
    {listFields.map((field) => <div key={field}>
      <label htmlFor={`${fieldId}-${field}`}>{labels[field]}</label>
      <textarea id={`${fieldId}-${field}`} value={value[field]} maxLength={10020} rows={3}
        onChange={(event) => onChange({ ...value, [field]: event.target.value })} />
    </div>)}
    <p>Starting knowledge describes what the character believes they already know. It does not change world facts.</p>
  </fieldset>;
}
