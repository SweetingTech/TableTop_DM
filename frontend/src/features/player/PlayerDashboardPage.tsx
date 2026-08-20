import {
  Dices,
  FileUp,
  HeartPulse,
  Plus,
  ScrollText,
  Shield,
  Sparkles,
  Swords,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { EmptyState, LoadingState } from "../../components/ui/States";
import { PageHeader, Status } from "../../components/ui/Primitives";
import * as api from "./api";
import type { CharacterRecord, HostedGame } from "./api";

const abilities = [
  "strength",
  "dexterity",
  "constitution",
  "intelligence",
  "wisdom",
  "charisma",
];
const initialScores = Object.fromEntries(
  abilities.map((ability) => [ability, 10]),
);

export default function PlayerDashboardPage() {
  const [characters, setCharacters] = useState<CharacterRecord[]>([]);
  const [games, setGames] = useState<HostedGame[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [mode, setMode] = useState<"LIST" | "BUILD" | "GENERATE" | "IMPORT">(
    "LIST",
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function reload() {
    setLoading(true);
    try {
      const [characterRows, gameRows] = await Promise.all([
        api.listCharacters(),
        api.listGames(),
      ]);
      setCharacters(characterRows);
      setGames(gameRows);
      setSelectedId((current) =>
        characterRows.some((row) => row.character_id === current)
          ? current
          : (characterRows[0]?.character_id ?? ""),
      );
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to load player dashboard",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    const pending = window.setTimeout(() => void reload(), 0);
    return () => window.clearTimeout(pending);
  }, []);
  const selected =
    characters.find((row) => row.character_id === selectedId) ?? null;

  async function operation(work: () => Promise<unknown>, success: string) {
    setError("");
    setMessage("");
    try {
      await work();
      setMessage(success);
      setMode("LIST");
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Operation failed");
    }
  }

  return (
    <div className="page player-page">
      <PageHeader
        title="Player Dashboard"
        description="Your characters, adventuring status, active games, and character creation tools."
        actions={
          <div className="page-actions">
            <button
              className="button"
              type="button"
              onClick={() => setMode("IMPORT")}
            >
              <FileUp size={15} />
              Import
            </button>
            <button
              className="button"
              type="button"
              onClick={() => setMode("GENERATE")}
            >
              <Sparkles size={15} />
              Generate
            </button>
            <button
              className="button primary"
              type="button"
              onClick={() => setMode("BUILD")}
            >
              <Plus size={15} />
              Build character
            </button>
          </div>
        }
      />
      {error || message ? (
        <div
          className={`toast ${error ? "error" : "success"}`}
          role={error ? "alert" : "status"}
        >
          {error || message}
        </div>
      ) : null}
      {mode === "BUILD" ? (
        <CharacterBuilder
          onSave={(payload) =>
            operation(() => api.createCharacter(payload), "Character created.")
          }
          onCancel={() => setMode("LIST")}
        />
      ) : null}
      {mode === "GENERATE" ? (
        <CharacterGenerator
          onSave={(payload) =>
            operation(
              () => api.createCharacter(payload),
              "Character generated.",
            )
          }
          onCancel={() => setMode("LIST")}
        />
      ) : null}
      {mode === "IMPORT" ? (
        <CharacterImporter
          onSave={(payload) =>
            operation(() => api.createCharacter(payload), "Character imported.")
          }
          onCancel={() => setMode("LIST")}
        />
      ) : null}
      <div className="player-layout">
        <section className="panel character-library">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Character vault</span>
              <h2>Saved characters</h2>
            </div>
            <ScrollText size={18} />
          </div>
          {loading ? (
            <LoadingState label="Loading characters" />
          ) : characters.length ? (
            <div className="character-grid">
              {characters.map((character) => (
                <button
                  type="button"
                  key={character.character_id}
                  className={`character-card ${selectedId === character.character_id ? "selected" : ""}`}
                  onClick={() => setSelectedId(character.character_id)}
                >
                  <div className="character-card-top">
                    <span className="character-monogram">
                      {character.name.slice(0, 1)}
                    </span>
                    <Status value={character.status} />
                  </div>
                  <strong>{character.name}</strong>
                  <small>
                    Level {character.level} {character.species}{" "}
                    {character.class_name}
                  </small>
                  <div className="character-vitals">
                    <span>
                      <HeartPulse size={13} />
                      {character.current_hit_points}/
                      {character.maximum_hit_points}
                    </span>
                    <span>
                      <Shield size={13} />
                      AC {character.armor_class}
                    </span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No saved characters"
              detail="Build, generate, or import your first adventurer."
            />
          )}
        </section>
        <section className="panel character-sheet-panel">
          {selected ? (
            <CharacterSheet
              key={selected.character_id}
              character={selected}
              onUpdate={(payload) =>
                operation(
                  () => api.updateCharacter(selected.character_id, payload),
                  "Character updated.",
                )
              }
              onDelete={() =>
                operation(
                  () => api.deleteCharacter(selected.character_id),
                  "Character deleted.",
                )
              }
            />
          ) : (
            <EmptyState
              title="Choose a character"
              detail="Character stats and status will appear here."
            />
          )}
        </section>
        <section className="panel player-games">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Table status</span>
              <h2>My games</h2>
            </div>
            <Swords size={18} />
          </div>
          {games.length ? (
            <div className="stack-list">
              {games.map((game) => (
                <article className="stack-row" key={game.game_id}>
                  <span className="row-icon">
                    <Dices size={16} />
                  </span>
                  <div>
                    <strong>{game.name}</strong>
                    <small>
                      {game.members.length}/{game.max_players} players ·{" "}
                      {game.description || "No campaign summary"}
                    </small>
                  </div>
                  <Status value={game.status} />
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No game invitations"
              detail="A Dungeon Master can add this account to a hosted game."
            />
          )}
        </section>
      </div>
    </div>
  );
}

function CharacterSheet({
  character,
  onUpdate,
  onDelete,
}: {
  character: CharacterRecord;
  onUpdate: (payload: Record<string, unknown>) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [status, setStatus] = useState(character.status);
  const [hp, setHp] = useState(character.current_hit_points);
  return (
    <div className="character-sheet">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Character sheet</span>
          <h2>{character.name}</h2>
          <p>
            {character.background} · {character.creation_method.toLowerCase()}
          </p>
        </div>
        <Status value={character.status} />
      </div>
      <div className="sheet-hero">
        <div>
          <span>Level</span>
          <strong>{character.level}</strong>
        </div>
        <div>
          <span>Armor class</span>
          <strong>{character.armor_class}</strong>
        </div>
        <div>
          <span>Speed</span>
          <strong>{character.speed}</strong>
        </div>
        <div>
          <span>Hit points</span>
          <strong>
            {character.current_hit_points}/{character.maximum_hit_points}
          </strong>
        </div>
      </div>
      <div className="ability-grid">
        {abilities.map((ability) => (
          <div key={ability}>
            <span>{ability.slice(0, 3).toUpperCase()}</span>
            <strong>{character.ability_scores[ability] ?? 10}</strong>
            <small>
              {Math.floor(
                ((character.ability_scores[ability] ?? 10) - 10) / 2,
              ) >= 0
                ? "+"
                : ""}
              {Math.floor(((character.ability_scores[ability] ?? 10) - 10) / 2)}
            </small>
          </div>
        ))}
      </div>
      <div className="sheet-controls">
        <label>
          Status
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as CharacterRecord["status"])
            }
          >
            <option>ALIVE</option>
            <option>DEAD</option>
            <option>MISSING</option>
            <option>RETIRED</option>
          </select>
        </label>
        <label>
          Current hit points
          <input
            type="number"
            min={0}
            max={character.maximum_hit_points}
            value={hp}
            onChange={(event) => setHp(Number(event.target.value))}
          />
        </label>
        <button
          className="button"
          type="button"
          onClick={() => void onUpdate({ status, current_hit_points: hp })}
        >
          Save status
        </button>
      </div>
      <button
        className="button danger subtle-danger"
        type="button"
        onClick={() => {
          if (window.confirm(`Delete ${character.name}?`)) void onDelete();
        }}
      >
        <Trash2 size={14} />
        Delete character
      </button>
    </div>
  );
}

function CharacterBuilder({
  onSave,
  onCancel,
}: {
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [species, setSpecies] = useState("Human");
  const [className, setClassName] = useState("Fighter");
  const [background, setBackground] = useState("Adventurer");
  const [scores, setScores] = useState<Record<string, number>>(initialScores);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSave({
      creation_method: "BUILT",
      name,
      species,
      class_name: className,
      background,
      ability_scores: scores,
      maximum_hit_points: 10,
      current_hit_points: 10,
    });
  }
  return (
    <section className="panel creation-workspace">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Guided creation</span>
          <h2>Build a character</h2>
        </div>
      </div>
      <form className="character-form" onSubmit={submit}>
        <div className="form-pair">
          <label>
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Species
            <input
              value={species}
              onChange={(event) => setSpecies(event.target.value)}
            />
          </label>
        </div>
        <div className="form-pair">
          <label>
            Class
            <input
              value={className}
              onChange={(event) => setClassName(event.target.value)}
            />
          </label>
          <label>
            Background
            <input
              value={background}
              onChange={(event) => setBackground(event.target.value)}
            />
          </label>
        </div>
        <div className="score-builder">
          {abilities.map((ability) => (
            <label key={ability}>
              {ability.slice(0, 3).toUpperCase()}
              <input
                type="number"
                min={1}
                max={30}
                value={scores[ability]}
                onChange={(event) =>
                  setScores((current) => ({
                    ...current,
                    [ability]: Number(event.target.value),
                  }))
                }
              />
            </label>
          ))}
        </div>
        <div className="form-actions">
          <button className="button primary" type="submit" disabled={!name}>
            Save character
          </button>
          <button className="button" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

function CharacterGenerator({
  onSave,
  onCancel,
}: {
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1_000_000));
  return (
    <section className="panel creation-workspace">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Seeded generator</span>
          <h2>Generate an adventurer</h2>
          <p>
            Creates a reproducible level-one character you can edit afterward.
          </p>
        </div>
        <Sparkles size={18} />
      </div>
      <label>
        Generation seed
        <input
          type="number"
          value={seed}
          onChange={(event) => setSeed(Number(event.target.value))}
        />
      </label>
      <div className="form-actions">
        <button
          className="button primary"
          type="button"
          onClick={() => void onSave({ creation_method: "GENERATED", seed })}
        >
          <Sparkles size={15} />
          Generate and save
        </button>
        <button className="button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}

function CharacterImporter({
  onSave,
  onCancel,
}: {
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const [payload, setPayload] = useState<Record<string, unknown> | null>(null);
  const [filename, setFilename] = useState("");
  const [error, setError] = useState("");
  async function read(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 1_000_000) {
      setError("Character templates must be smaller than 1 MB.");
      return;
    }
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      setPayload(parsed);
      setFilename(file.name);
      setError("");
    } catch {
      setError("Upload a JSON character template.");
      setPayload(null);
    }
  }
  return (
    <section className="panel creation-workspace">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Template import</span>
          <h2>Upload a character</h2>
          <p>
            Import a JSON character template. You can revise the saved sheet
            afterward.
          </p>
        </div>
        <FileUp size={18} />
      </div>
      <label className="upload-zone">
        <FileUp size={22} />
        <span>{filename || "Choose a JSON character template"}</span>
        <input
          type="file"
          accept="application/json,.json"
          onChange={(event) => void read(event)}
        />
      </label>
      {error ? (
        <p className="field-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="form-actions">
        <button
          className="button primary"
          type="button"
          disabled={!payload}
          onClick={() =>
            payload &&
            void onSave({
              ...payload,
              creation_method: "IMPORTED",
              source_filename: filename,
            })
          }
        >
          Import and save
        </button>
        <button className="button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </section>
  );
}
