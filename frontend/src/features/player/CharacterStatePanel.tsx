import { useState, type FormEvent } from "react";
import { Status } from "../../components/ui/Primitives";
import { LoadingState } from "../../components/ui/States";
import type { CharacterRecord } from "./api";
import { useCharacterState } from "./useCharacterState";

export function CharacterStatePanel({ character, onUpdate }: {
  character: CharacterRecord; onUpdate: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const { data, error, loading, refresh } = useCharacterState(character);
  const body = data?.source === "KERNEL" ? data.body : null;
  const authored = data?.source === "AUTHORED";
  const inventory = body ? Object.entries(body.inventory).filter(([, amount]) => amount > 0) : [];
  return <section aria-label="Character resources">
    <div className="panel-heading">
      <span className="section-kicker">{body ? "Campaign state" : authored ? "Character card" : "Character state"}</span>
      {data ? <Status value={body?.status ?? character.status} /> : null}
      <button className="button" type="button" aria-label="Refresh character state" aria-disabled={loading}
        onClick={() => { if (!loading) refresh(); }}>Refresh</button>
    </div>
    {loading ? <LoadingState label="Loading character state" /> : null}
    {error ? <p role="alert">{error}</p> : null}
    {data ? <>
      <div className="sheet-hero">
        <div><span>Level</span><strong>{character.level}</strong></div>
        <div><span>Armor class</span><strong>{body?.armor ?? character.armor_class}</strong></div>
        <div><span>Speed</span><strong>{body?.speed ?? character.speed}</strong></div>
        <div><span>Hit points</span><strong aria-label="Character hit points">{body ? `${body.hp}/${body.max_hp}` : `${character.current_hit_points}/${character.maximum_hit_points}`}</strong></div>
      </div>
      {body ? <div className="stack-list">
        <p>Health, status and equipment follow in-game actions.</p>
        <p>Mana: <strong>{body.mana}</strong></p>
        <p>Equipped weapon: <strong style={{ overflowWrap: "anywhere" }}>{body.equipped_weapon.replaceAll("_", " ")}</strong></p>
        <p>Learned spells: {body.known_spells.length ? body.known_spells.map((spell) => spell.replaceAll("_", " ")).join(", ") : "None"}</p>
        <p>Conditions: {body.conditions.length ? body.conditions.join(", ") : "None"}</p>
        {body.attack_bonus != null ? <p>Attack bonus: <strong>{body.attack_bonus >= 0 ? "+" : ""}{body.attack_bonus}</strong>
          {body.damage_bonus != null ? <> · Damage bonus: <strong>{body.damage_bonus >= 0 ? "+" : ""}{body.damage_bonus}</strong></> : null}</p> : null}
        <div aria-label="Inventory" style={{ maxHeight: "16rem", overflowY: "auto", overflowWrap: "anywhere" }}>
          <strong>Inventory</strong>
          {inventory.length ? <ul>{inventory.map(([item, amount]) => <li key={item}>{item}: {amount}</li>)}</ul> : <p>Empty</p>}
        </div>
      </div> : null}
      {body?.ability_scores ? <Abilities scores={body.ability_scores} label="Campaign abilities" />
        : authored ? <Abilities scores={character.ability_scores} label="Starting abilities" />
        : body ? <p>Ability scores are not configured for this body.</p> : null}
    </> : null}
    <div hidden={!authored}>
      <StartingResources key={[character.character_id, character.status, character.current_hit_points,
        character.maximum_hit_points].join(":")} character={character} onUpdate={onUpdate} />
    </div>
  </section>;
}

const abilityNames = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"];
function Abilities({ scores, label }: { scores: Record<string, number>; label: string }) {
  return <div className="ability-grid" role="group" aria-label={label}>
    {abilityNames.map((ability) => {
      const score = scores[ability] ?? 10;
      const modifier = Math.floor((score - 10) / 2);
      return <div key={ability}><span>{ability.slice(0, 3).toUpperCase()}</span>
        <strong>{score}</strong><small>{modifier >= 0 ? "+" : ""}{modifier}</small></div>;
    })}
  </div>;
}

function StartingResources({ character, onUpdate }: {
  character: CharacterRecord; onUpdate: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [status, setStatus] = useState(character.status);
  const [hp, setHp] = useState(character.current_hit_points);
  const [saving, setSaving] = useState(false);
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true);
    try { await onUpdate({ status, current_hit_points: hp }); } finally { setSaving(false); }
  }
  return <form className="sheet-controls" onSubmit={(event) => void save(event)}>
    <label>Status<select value={status} onChange={(event) => setStatus(event.target.value as CharacterRecord["status"])}>
      <option>ALIVE</option><option>DEAD</option><option>MISSING</option><option>RETIRED</option>
    </select></label>
    <label>Current hit points<input type="number" min={0} max={character.maximum_hit_points} value={hp}
      onChange={(event) => setHp(Number(event.target.value))} /></label>
    <button className="button" type="submit" disabled={saving}>{saving ? "Saving…" : "Save status"}</button>
  </form>;
}
