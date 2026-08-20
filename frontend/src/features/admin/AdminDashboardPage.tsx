import { KeyRound, Trash2, UserPlus, Users } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useAppContext } from "../../app/AppContext";
import { EmptyState, LoadingState } from "../../components/ui/States";
import { PageHeader, Status } from "../../components/ui/Primitives";
import type { CurrentUser } from "../auth/types";
import * as api from "./api";

const emptyProfile = {
  display_name: "",
  legal_name: "",
  email: "",
  date_of_birth: "",
  pronouns: "",
  timezone: "UTC",
  locale: "en-US",
  bio: "",
  avatar_uri: "",
};

export default function AdminDashboardPage() {
  const { worlds, activeWorldId } = useAppContext();
  const [users, setUsers] = useState<CurrentUser[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  async function reload() {
    setLoading(true);
    try {
      const rows = await api.listUsers();
      setUsers(rows);
      setSelectedId((current) =>
        rows.some((row) => row.user_id === current)
          ? current
          : (rows[0]?.user_id ?? ""),
      );
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to load accounts",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const pending = window.setTimeout(() => void reload(), 0);
    return () => window.clearTimeout(pending);
  }, []);
  const selected = users.find((row) => row.user_id === selectedId) ?? null;
  const roleTotals = useMemo(
    () => ({
      admins: users.filter((row) => row.is_admin).length,
      dms: users.filter((row) => row.has_dm_role).length,
      players: users.filter((row) => row.has_player_role).length,
    }),
    [users],
  );

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
    <div className="page admin-page">
      <PageHeader
        title="Admin Dashboard"
        description="Manage accounts, access, passwords, and world-scoped tabletop roles."
        actions={
          <button
            className="button primary"
            type="button"
            onClick={() => setShowCreate((value) => !value)}
          >
            <UserPlus size={16} />
            Add account
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
      <div className="stat-strip admin-stats">
        <div className="stat">
          <span>Accounts</span>
          <strong>{users.length}</strong>
        </div>
        <div className="stat">
          <span>Admins</span>
          <strong>{roleTotals.admins}</strong>
        </div>
        <div className="stat">
          <span>Dungeon Masters</span>
          <strong>{roleTotals.dms}</strong>
        </div>
        <div className="stat">
          <span>Players</span>
          <strong>{roleTotals.players}</strong>
        </div>
      </div>
      {showCreate ? (
        <CreateAccount
          onCancel={() => setShowCreate(false)}
          onCreate={(input) =>
            operation(
              () => api.createUser(input),
              "Account created. The user must change the temporary password at sign in.",
            ).then(() => setShowCreate(false))
          }
        />
      ) : null}
      <div className="admin-layout">
        <section className="panel admin-user-list">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">Directory</span>
              <h2>Accounts</h2>
            </div>
            <Users size={18} />
          </div>
          {loading ? (
            <LoadingState label="Loading accounts" />
          ) : users.length ? (
            <div className="selection-list">
              {users.map((user) => (
                <button
                  type="button"
                  className={`selection-row ${selectedId === user.user_id ? "selected" : ""}`}
                  key={user.user_id}
                  onClick={() => setSelectedId(user.user_id)}
                >
                  <span className="entity-sigil">
                    <Users size={15} />
                  </span>
                  <span>
                    <strong>{user.profile.display_name}</strong>
                    <small>
                      @{user.username} ·{" "}
                      {user.is_admin
                        ? "Administrator"
                        : user.has_dm_role && user.has_player_role
                          ? "DM + Player"
                          : user.has_dm_role
                            ? "Dungeon Master"
                            : "Player"}
                    </small>
                  </span>
                  <Status value={user.is_active ? "ACTIVE" : "DISABLED"} />
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No accounts"
              detail="Create the first player or Dungeon Master account."
            />
          )}
        </section>
        <section className="panel admin-account-detail">
          {selected ? (
            <AccountEditor
              key={selected.user_id}
              user={selected}
              worlds={worlds}
              activeWorldId={activeWorldId}
              onOperation={operation}
            />
          ) : (
            <EmptyState
              title="Select an account"
              detail="Choose an account to edit profile, access, or password."
            />
          )}
        </section>
      </div>
    </div>
  );
}

function CreateAccount({
  onCreate,
  onCancel,
}: {
  onCreate: (input: {
    username: string;
    temporary_password: string;
    profile: typeof emptyProfile;
  }) => Promise<void>;
  onCancel: () => void;
}) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    await onCreate({
      username,
      temporary_password: password,
      profile: { ...emptyProfile, display_name: displayName },
    });
  }
  return (
    <section className="panel admin-create">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">New identity</span>
          <h2>Create account</h2>
        </div>
      </div>
      <form className="management-form" onSubmit={submit}>
        <label>
          Display name
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label>
          Username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label>
          Temporary password
          <input
            type="password"
            minLength={12}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <p className="management-note">
          The user will be required to replace this password at first sign in.
        </p>
        <div className="form-actions">
          <button
            className="button primary"
            type="submit"
            disabled={
              !displayName || username.length < 3 || password.length < 12
            }
          >
            Create account
          </button>
          <button className="button" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

function AccountEditor({
  user,
  worlds,
  activeWorldId,
  onOperation,
}: {
  user: CurrentUser;
  worlds: { world_id: string; name: string }[];
  activeWorldId: string;
  onOperation: (work: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [worldId, setWorldId] = useState(
    activeWorldId || worlds[0]?.world_id || "",
  );
  const grants =
    user.world_roles.find((grant) => grant.world_id === worldId)?.roles ?? [];
  const [dm, setDm] = useState(grants.includes("DM"));
  const [player, setPlayer] = useState(grants.includes("PLAYER"));
  function selectWorld(nextWorldId: string) {
    setWorldId(nextWorldId);
    const nextRoles =
      user.world_roles.find((grant) => grant.world_id === nextWorldId)?.roles ??
      [];
    setDm(nextRoles.includes("DM"));
    setPlayer(nextRoles.includes("PLAYER"));
  }
  return (
    <div className="account-editor">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">Account</span>
          <h2>{user.profile.display_name}</h2>
          <p>@{user.username}</p>
        </div>
        <Status value={user.is_active ? "ACTIVE" : "DISABLED"} />
      </div>
      <div className="account-summary">
        <div>
          <span>Created</span>
          <strong>{new Date(user.created_at).toLocaleDateString()}</strong>
        </div>
        <div>
          <span>Last sign in</span>
          <strong>
            {user.last_login_at
              ? new Date(user.last_login_at).toLocaleString()
              : "Never"}
          </strong>
        </div>
      </div>
      <section className="account-section">
        <h3>Account access</h3>
        <label className="check-row">
          <input
            type="checkbox"
            checked={user.is_admin}
            onChange={(event) =>
              void onOperation(
                () =>
                  api.setGlobalRoles(
                    user.user_id,
                    event.target.checked ? ["ADMIN"] : [],
                  ),
                "Administrator access updated.",
              )
            }
          />
          <span>
            <strong>Administrator</strong>
            <small>Manage every account, role, and simulation workspace.</small>
          </span>
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={user.is_active}
            onChange={(event) =>
              void onOperation(
                () =>
                  api.updateUser(user.user_id, {
                    is_active: event.target.checked,
                  }),
                "Account status updated.",
              )
            }
          />
          <span>
            <strong>Account enabled</strong>
            <small>Disabled accounts are signed out immediately.</small>
          </span>
        </label>
      </section>
      <section className="account-section">
        <h3>World roles</h3>
        <label>
          World
          <select
            value={worldId}
              onChange={(event) => selectWorld(event.target.value)}
          >
            {worlds.map((world) => (
              <option key={world.world_id} value={world.world_id}>
                {world.name}
              </option>
            ))}
          </select>
        </label>
        <div className="role-grid">
          <label className="check-row">
            <input
              type="checkbox"
              checked={dm}
              onChange={(event) => setDm(event.target.checked)}
            />
            <span>
              <strong>Dungeon Master</strong>
              <small>
                Host games, manage rosters, sessions, encounters, NPCs, and
                rulings.
              </small>
            </span>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={player}
              onChange={(event) => setPlayer(event.target.checked)}
            />
            <span>
              <strong>Player</strong>
              <small>
                Create characters, join games, and use player game tools.
              </small>
            </span>
          </label>
        </div>
        <button
          className="button"
          type="button"
          disabled={!worldId}
          onClick={() =>
            void onOperation(
              () =>
                api.setWorldRoles(user.user_id, worldId, [
                  ...(dm ? ["DM"] : []),
                  ...(player ? ["PLAYER"] : []),
                ]),
              "World roles updated.",
            )
          }
        >
          Save world roles
        </button>
      </section>
      <section className="account-section">
        <h3>Password reset</h3>
        <div className="inline-action">
          <input
            aria-label="Temporary password"
            type="password"
            minLength={12}
            placeholder="New temporary password"
            value={temporaryPassword}
            onChange={(event) => setTemporaryPassword(event.target.value)}
          />
          <button
            className="button"
            type="button"
            disabled={temporaryPassword.length < 12}
            onClick={() =>
              void onOperation(
                () => api.resetPassword(user.user_id, temporaryPassword),
                "Password reset. Existing sessions were closed.",
              ).then(() => setTemporaryPassword(""))
            }
          >
            <KeyRound size={15} />
            Reset
          </button>
        </div>
        <p className="management-note">
          The user must change the temporary password at the next sign in.
        </p>
      </section>
      <section className="account-section danger-zone">
        <h3>Delete account</h3>
        <p>Removes the login while preserving authored simulation history.</p>
        <button
          className="button danger"
          type="button"
          onClick={() => {
            if (window.confirm(`Delete @${user.username}?`))
              void onOperation(
                () => api.deleteUser(user.user_id),
                "Account deleted.",
              );
          }}
        >
          <Trash2 size={15} />
          Delete account
        </button>
      </section>
    </div>
  );
}
