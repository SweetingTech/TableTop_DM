import { useState, type ReactNode } from "react";
import {
  Activity,
  Crown,
  FlaskConical,
  Gamepad2,
  Gauge,
  Globe2,
  Menu,
  PlayCircle,
  Settings,
  ShieldCheck,
  UserCog,
  Users,
  UserRound,
  X,
} from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { useAppContext } from "../app/AppContext";
import { useAuth } from "../features/auth/AuthContext";

const NAV_ITEMS = [
  {
    path: "/game",
    label: "Game Console",
    short: "Game",
    icon: Gamepad2,
    id: "nav-game",
    access: "game",
  },
  {
    path: "/player",
    label: "Player Dashboard",
    short: "Player",
    icon: UserRound,
    id: "nav-player",
    access: "player",
  },
  {
    path: "/dm",
    label: "Dungeon Master",
    short: "Dungeon Master",
    icon: Crown,
    id: "nav-dm",
    access: "dm",
  },
  {
    path: "/admin",
    label: "Admin Dashboard",
    short: "Admin",
    icon: UserCog,
    id: "nav-admin",
    access: "admin",
  },
  {
    path: "/control",
    label: "Control Plane",
    short: "Worlds",
    icon: Globe2,
    id: "nav-control",
    access: "admin",
  },
  {
    path: "/personas",
    label: "Persona Studio",
    short: "Personas",
    icon: ShieldCheck,
    id: "nav-personas",
    access: "admin",
  },
  {
    path: "/populations",
    label: "Population Studio",
    short: "Populations",
    icon: Users,
    id: "nav-populations",
    access: "admin",
  },
  {
    path: "/scenarios",
    label: "Scenario Lab",
    short: "Scenario Lab",
    icon: FlaskConical,
    id: "nav-scenarios",
    access: "admin",
  },
  {
    path: "/runs",
    label: "Run Inspector",
    short: "Runs",
    icon: PlayCircle,
    id: "nav-runs",
    access: "admin",
  },
  {
    path: "/calibration",
    label: "Calibration",
    short: "Calibration",
    icon: Gauge,
    id: "nav-calibration",
    access: "admin",
  },
  {
    path: "/settings",
    label: "Settings",
    short: "Settings",
    icon: Settings,
    id: "nav-settings",
    access: "all",
  },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const {
    worlds,
    activeWorldId,
    setActiveWorldId,
    source,
    sourceReason,
    loading,
    error,
    authorizationRequired,
  } = useAppContext();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const visibleItems = NAV_ITEMS.filter(
    (item) =>
      item.access === "all" ||
      item.access === "game" ||
      (item.access === "admin" && user?.is_admin) ||
      (item.access === "dm" && (user?.is_admin || user?.has_dm_role)) ||
      (item.access === "player" && (user?.is_admin || user?.has_player_role)),
  );
  const activeItem =
    visibleItems.find((item) => location.pathname.endsWith(item.path)) ??
    visibleItems[0] ??
    NAV_ITEMS.at(-1)!;
  const engineState = loading
    ? "Connecting to local engine"
    : authorizationRequired
      ? "Operator access required"
      : error
        ? "Local engine unavailable"
        : source === "live"
          ? "Local engine ready"
          : "Demo fallback active";

  return (
    <div className="app-shell" data-testid="app-shell">
      <header className="topbar">
        <button
          className="mobile-menu"
          type="button"
          aria-label={open ? "Close navigation" : "Open navigation"}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
        <NavLink className="brand" to="/game">
          TableTop Simulation Kernel
        </NavLink>
        <div className="topbar-divider" />
        <label className="context-control">
          <span>Active world</span>
          <select
            value={activeWorldId}
            disabled={loading || worlds.length === 0}
            onChange={(event) => setActiveWorldId(event.target.value)}
          >
            {worlds.map((world) => (
              <option key={world.world_id} value={world.world_id}>
                {world.name}
              </option>
            ))}
          </select>
        </label>
        <div className="context-control workspace-context">
          <span>Workspace</span>
          <strong>{activeItem.label}</strong>
        </div>
        <div
          className={`engine-state ${authorizationRequired || error ? "attention" : ""}`}
        >
          <span className="status-dot" />
          {engineState}
        </div>
      </header>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <nav aria-label="Primary navigation">
          {visibleItems.map(({ path, label, short, icon: Icon, id }) => (
            <NavLink
              aria-label={label}
              className={({ isActive }) =>
                isActive ? "nav-item selected" : "nav-item"
              }
              data-testid={id}
              key={path}
              onClick={() => setOpen(false)}
              to={path}
            >
              <Icon aria-hidden="true" size={20} strokeWidth={1.6} />
              <span>{short}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-health">
          <Activity size={17} aria-hidden="true" />
          <div>
            <strong>{user?.profile.display_name ?? "Signed in"}</strong>
            <span>
              {user?.is_admin
                ? "Administrator"
                : user?.has_dm_role && user?.has_player_role
                  ? "DM + Player"
                  : user?.has_dm_role
                    ? "Dungeon Master"
                    : "Player"}
            </span>
          </div>
        </div>
      </aside>
      {open ? (
        <button
          className="nav-scrim"
          type="button"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      ) : null}
      <main className="workspace">
        <span className="sr-only" aria-live="polite">
          {authorizationRequired
            ? "Operator access required"
            : error
              ? error
              : source === "demo"
                ? sourceReason
                : "Live kernel data connected"}
        </span>
        {children}
      </main>
    </div>
  );
}
