import {
  BookOpen,
  CalendarClock,
  Crown,
  Eye,
  Play,
  Plus,
  ShieldAlert,
  Swords,
  UserPlus,
  Users,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useAppContext } from "../../app/AppContext";
import { EmptyState, LoadingState } from "../../components/ui/States";
import { PageHeader, Status } from "../../components/ui/Primitives";
import type { CurrentUser } from "../auth/types";
import type { HostedGame } from "../player/api";
import * as api from "./api";
import type { HostedSession } from "./api";

export default function DungeonMasterPage() {
  const { worlds, activeWorldId } = useAppContext();
  const [games, setGames] = useState<HostedGame[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [sessions, setSessions] = useState<HostedSession[]>([]);
  const [eligible, setEligible] = useState<CurrentUser[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function reload() {
    setLoading(true);
    try {
      const rows = await api.listGames();
      setGames(rows);
      const nextId = rows.some((row) => row.game_id === selectedId)
        ? selectedId
        : (rows[0]?.game_id ?? "");
      setSelectedId(nextId);
      const selected = rows.find((row) => row.game_id === nextId);
      if (selected) {
        const [sessionRows, userRows] = await Promise.all([
          api.listSessions(selected.game_id),
          api.eligibleUsers(selected.world_id),
        ]);
        setSessions(sessionRows);
        setEligible(userRows);
      } else {
        setSessions([]);
        setEligible([]);
      }
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Unable to load DM dashboard",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    const pending = window.setTimeout(() => void reload(), 0);
    return () => window.clearTimeout(pending);
    // The reload closure intentionally tracks the selected game identifier.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);
  const selected = games.find((row) => row.game_id === selectedId) ?? null;
  async function operation(work: () => Promise<unknown>, success: string) {
    setError("");
    setMessage("");
    try {
      await work();
      setMessage(success);
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Operation failed");
    }
  }

  return (
    <div className="page dm-page">
      <PageHeader
        title="Dungeon Master"
        description="Prepare campaigns, host live games, manage players, and run sessions from behind the screen."
        actions={
          <button
            className="button primary"
            type="button"
            onClick={() => setShowCreate((value) => !value)}
          >
            <Plus size={15} />
            Host a game
          </button>
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
      <div className="dm-tool-rail">
        <div>
          <Crown />
          <span>Campaign authority</span>
          <strong>Narrate, adjudicate, and pace</strong>
        </div>
        <div>
          <Swords />
          <span>Encounter control</span>
          <strong>Initiative, monsters, and outcomes</strong>
        </div>
        <div>
          <Eye />
          <span>Hidden information</span>
          <strong>DM notes, secrets, and NPC intent</strong>
        </div>
        <div>
          <ShieldAlert />
          <span>Table safety</span>
          <strong>Boundaries and session expectations</strong>
        </div>
      </div>
      {showCreate ? (
        <CreateGame
          worlds={worlds.filter((world) =>
            activeWorldId ? world.world_id === activeWorldId : true,
          )}
          onCancel={() => setShowCreate(false)}
          onSave={(payload) =>
            operation(() => api.createGame(payload), "Game created.").then(() =>
              setShowCreate(false),
            )
          }
        />
      ) : null}
      <div className="dm-layout">
        <section className="panel dm-game-list">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Campaigns</span>
              <h2>Hosted games</h2>
            </div>
            <BookOpen size={18} />
          </div>
          {loading ? (
            <LoadingState label="Loading hosted games" />
          ) : games.length ? (
            <div className="selection-list">
              {games.map((game) => (
                <button
                  type="button"
                  className={`selection-row ${selectedId === game.game_id ? "selected" : ""}`}
                  key={game.game_id}
                  onClick={() => setSelectedId(game.game_id)}
                >
                  <span className="entity-sigil">
                    <Crown size={15} />
                  </span>
                  <span>
                    <strong>{game.name}</strong>
                    <small>
                      {game.members.length}/{game.max_players} seats ·{" "}
                      {game.description || "No summary"}
                    </small>
                  </span>
                  <Status value={game.status} />
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No hosted games"
              detail="Create a game for a world where you have the DM role."
            />
          )}
        </section>
        <section className="panel dm-command">
          {selected ? (
            <GameCommand
              game={selected}
              sessions={sessions}
              eligible={eligible}
              onOperation={operation}
            />
          ) : (
            <EmptyState
              title="Select a game"
              detail="Game status, roster, and session controls will appear here."
            />
          )}
        </section>
      </div>
    </div>
  );
}

function CreateGame({
  worlds,
  onSave,
  onCancel,
}: {
  worlds: { world_id: string; name: string }[];
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const [worldId, setWorldId] = useState(worlds[0]?.world_id ?? "");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    await onSave({ world_id: worldId, name, description });
  }
  return (
    <section className="panel creation-workspace">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">New campaign table</span>
          <h2>Host a game</h2>
        </div>
      </div>
      <form className="management-form" onSubmit={submit}>
        <label>
          World
          <select
            value={worldId}
            onChange={(event) => setWorldId(event.target.value)}
          >
            {worlds.map((world) => (
              <option key={world.world_id} value={world.world_id}>
                {world.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Game name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="management-description">
          Description
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div className="form-actions">
          <button
            className="button primary"
            disabled={!worldId || !name}
            type="submit"
          >
            Create game
          </button>
          <button className="button" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

function GameCommand({
  game,
  sessions,
  eligible,
  onOperation,
}: {
  game: HostedGame;
  sessions: HostedSession[];
  eligible: CurrentUser[];
  onOperation: (work: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const [memberId, setMemberId] = useState(
    eligible.find(
      (user) => !game.members.some((member) => member.user_id === user.user_id),
    )?.user_id ?? "",
  );
  const [sessionTitle, setSessionTitle] = useState("");
  const available = eligible.filter(
    (user) => !game.members.some((member) => member.user_id === user.user_id),
  );
  return (
    <div className="dm-game-command">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Live table</span>
          <h2>{game.name}</h2>
          <p>{game.description || "No campaign summary yet."}</p>
        </div>
        <Status value={game.status} />
      </div>
      <div className="game-status-actions">
        <button
          className="button primary"
          type="button"
          disabled={game.status === "LIVE"}
          onClick={() =>
            void onOperation(
              () => api.updateGame(game.game_id, { status: "LIVE" }),
              "Game is live.",
            )
          }
        >
          <Play size={14} />
          Start game
        </button>
        <button
          className="button"
          type="button"
          onClick={() =>
            void onOperation(
              () => api.updateGame(game.game_id, { status: "PAUSED" }),
              "Game paused.",
            )
          }
        >
          Pause
        </button>
        <button
          className="button"
          type="button"
          onClick={() =>
            void onOperation(
              () => api.updateGame(game.game_id, { status: "COMPLETED" }),
              "Game completed.",
            )
          }
        >
          Complete
        </button>
      </div>
      <section className="dm-section">
        <div className="section-title">
          <div>
            <span className="section-kicker">Roster</span>
            <h3>Players in game</h3>
          </div>
          <Users size={17} />
        </div>
        {game.members.length ? (
          <div className="stack-list">
            {game.members.map((member) => (
              <article className="stack-row" key={member.user_id}>
                <span className="row-icon">
                  <Users size={15} />
                </span>
                <div>
                  <strong>{member.display_name}</strong>
                  <small>
                    {member.membership_role === "CO_DM"
                      ? "Co-DM"
                      : member.character_name || "No character assigned"}
                  </small>
                </div>
                <Status value={member.status} />
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No players yet"
            detail="Invite a player or co-DM with a role in this world."
          />
        )}
        <div className="inline-action">
          <select
            aria-label="Eligible user"
            value={memberId}
            onChange={(event) => setMemberId(event.target.value)}
          >
            <option value="">Select a player or DM</option>
            {available.map((user) => (
              <option key={user.user_id} value={user.user_id}>
                {user.profile.display_name} ·{" "}
                {user.has_dm_role ? "DM" : "Player"}
              </option>
            ))}
          </select>
          <button
            className="button"
            disabled={!memberId}
            type="button"
            onClick={() =>
              void onOperation(
                () =>
                  api.setMember(game.game_id, {
                    user_id: memberId,
                    membership_role: eligible.find(
                      (user) => user.user_id === memberId,
                    )?.has_dm_role
                      ? "CO_DM"
                      : "PLAYER",
                    status: "INVITED",
                  }),
                "Roster updated.",
              )
            }
          >
            <UserPlus size={14} />
            Invite
          </button>
        </div>
      </section>
      <section className="dm-section">
        <div className="section-title">
          <div>
            <span className="section-kicker">Schedule and play</span>
            <h3>Sessions</h3>
          </div>
          <CalendarClock size={17} />
        </div>
        {sessions.length ? (
          <div className="session-list">
            {sessions.map((session) => (
              <article key={session.session_id}>
                <div>
                  <strong>{session.title}</strong>
                  <small>
                    {session.scheduled_for
                      ? new Date(session.scheduled_for).toLocaleString()
                      : "Unscheduled"}
                  </small>
                </div>
                <Status value={session.status} />
                <div className="session-actions">
                  <button
                    type="button"
                    onClick={() =>
                      void onOperation(
                        () =>
                          api.updateSession(game.game_id, session.session_id, {
                            status: "LIVE",
                          }),
                        "Session started.",
                      )
                    }
                  >
                    Start
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void onOperation(
                        () =>
                          api.updateSession(game.game_id, session.session_id, {
                            status: "COMPLETED",
                          }),
                        "Session completed.",
                      )
                    }
                  >
                    Complete
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No sessions scheduled"
            detail="Prepare the next session, then start it when the table is ready."
          />
        )}
        <div className="inline-action">
          <input
            aria-label="Session title"
            placeholder="Session title"
            value={sessionTitle}
            onChange={(event) => setSessionTitle(event.target.value)}
          />
          <button
            className="button"
            type="button"
            disabled={!sessionTitle}
            onClick={() =>
              void onOperation(
                () => api.createSession(game.game_id, { title: sessionTitle }),
                "Session scheduled.",
              ).then(() => setSessionTitle(""))
            }
          >
            <Plus size={14} />
            Add session
          </button>
        </div>
      </section>
    </div>
  );
}
