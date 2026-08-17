import { useState, type ReactNode } from "react";
import { Activity, FlaskConical, Gamepad2, Gauge, Globe2, Menu, PlayCircle, Settings, Users, UserRound, X } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { useAppContext } from "../app/AppContext";

const NAV_ITEMS = [
  { path: "/game", label: "Game Console", short: "Game", icon: Gamepad2, id: "nav-game" },
  { path: "/control", label: "Control Plane", short: "Worlds", icon: Globe2, id: "nav-control" },
  { path: "/personas", label: "Persona Studio", short: "Personas", icon: UserRound, id: "nav-personas" },
  { path: "/populations", label: "Population Studio", short: "Populations", icon: Users, id: "nav-populations" },
  { path: "/scenarios", label: "Scenario Lab", short: "Scenario Lab", icon: FlaskConical, id: "nav-scenarios" },
  { path: "/runs", label: "Run Inspector", short: "Runs", icon: PlayCircle, id: "nav-runs" },
  { path: "/calibration", label: "Calibration", short: "Calibration", icon: Gauge, id: "nav-calibration" },
  { path: "/settings", label: "Settings", short: "Settings", icon: Settings, id: "nav-settings" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { worlds, activeWorldId, setActiveWorldId, source, sourceReason, loading } = useAppContext();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const activeItem = NAV_ITEMS.find((item) => location.pathname.endsWith(item.path)) ?? NAV_ITEMS[0];
  const activeWorld = worlds.find((world) => world.world_id === activeWorldId);

  return (
    <div className="app-shell" data-testid="app-shell">
      <header className="topbar">
        <button className="mobile-menu" type="button" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
        <NavLink className="brand" to="/game">TableTop Simulation Kernel</NavLink>
        <div className="topbar-divider" />
        <label className="context-control">
          <span>Active world</span>
          <select value={activeWorldId} disabled={loading || worlds.length === 0} onChange={(event) => setActiveWorldId(event.target.value)}>
            {worlds.map((world) => <option key={world.world_id} value={world.world_id}>{world.name}</option>)}
          </select>
        </label>
        <div className="context-control workspace-context">
          <span>Workspace</span>
          <strong>{activeItem.label}</strong>
        </div>
        <div className="engine-state"><span className="status-dot" />{source === "live" ? "Local engine ready" : "Demo fallback active"}</div>
      </header>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <nav aria-label="Primary navigation">
          {NAV_ITEMS.map(({ path, label, short, icon: Icon, id }) => (
            <NavLink aria-label={label} className={({ isActive }) => isActive ? "nav-item selected" : "nav-item"} data-testid={id} key={path} onClick={() => setOpen(false)} to={path}>
              <Icon aria-hidden="true" size={20} strokeWidth={1.6} />
              <span>{short}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-health">
          <Activity size={17} aria-hidden="true" />
          <div><strong>{source === "live" ? "Local engine" : "Demo fixture"}</strong><span>{activeWorld?.name ?? "No active world"}</span></div>
        </div>
      </aside>
      {open ? <button className="nav-scrim" type="button" aria-label="Close navigation" onClick={() => setOpen(false)} /> : null}
      <main className="workspace">
        <span className="sr-only" aria-live="polite">{source === "demo" ? sourceReason : "Live kernel data connected"}</span>
        {children}
      </main>
    </div>
  );
}
