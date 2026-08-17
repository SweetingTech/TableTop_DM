import { useState } from "react";
import { Box, GitBranch, Plus, Save, Shield, Users } from "lucide-react";
import { useAppContext } from "../../app/AppContext";
import { DefinitionList, PageHeader, Panel, Stat, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type {
  ActorSummary,
  BranchSummary,
  EntitySummary,
  RunSummary,
  SnapshotSummary,
  Sourced,
  WorldSummary,
} from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import {
  createActor,
  createEntity,
  createRun,
  createSnapshot,
  createTrialBranch,
  createWorld,
  loadControlPlane,
} from "./api";

const TABS = ["Worlds", "Runs", "Actors & Capabilities", "Entities", "Snapshots", "Branches"] as const;
type Tab = typeof TABS[number];
type ExecuteAction = (label: string, action: () => Promise<Sourced<unknown>>) => Promise<void>;

export default function ControlPlanePage() {
  const { activeWorldId, refresh: refreshShell } = useAppContext();
  const resource = useAsyncResource(() => loadControlPlane(activeWorldId), [activeWorldId]);
  const [tab, setTab] = useState<Tab>("Worlds");
  const [worldName, setWorldName] = useState("");
  const [createdWorlds, setCreatedWorlds] = useState<WorldSummary[]>([]);
  const [workingAction, setWorkingAction] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionStatus, setActionStatus] = useState("");

  const execute: ExecuteAction = async (label, action) => {
    setWorkingAction(label);
    setActionError("");
    setActionStatus("");
    try {
      const result = await action();
      setActionStatus(
        result.source === "live"
          ? `${label} created and the live projection is reloading.`
          : `${label} created in deterministic demo mode.`,
      );
      if (result.source === "live") resource.reload();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : `${label} creation failed`);
    } finally {
      setWorkingAction("");
    }
  };

  async function submitWorld(event: React.FormEvent) {
    event.preventDefault();
    const name = worldName.trim();
    if (!name) return;
    await execute(`World “${name}”`, async () => {
      const result = await createWorld(name);
      if (result.source === "demo") setCreatedWorlds((current) => [...current, result.data]);
      else refreshShell();
      setWorldName("");
      return result;
    });
  }

  if (resource.loading) return <LoadingState label="Loading control plane" />;
  if (resource.error) return <ErrorState message={resource.error} retry={resource.reload} />;
  const payload = resource.data?.data;
  if (!payload) return <EmptyState title="No control data" detail="The kernel returned no management projections." />;
  const worlds = [...payload.worlds, ...createdWorlds];
  const selectedWorld = worlds.find((world) => world.world_id === activeWorldId) ?? worlds[0];
  const busy = Boolean(workingAction);

  return (
    <div className="page control-page">
      <SourceNotice source={resource.data?.source ?? "live"} reason={resource.data?.reason} />
      <PageHeader
        title="Control Plane"
        description="Manage worlds, authority, embodiments, runs, snapshots, and isolated trial branches."
        actions={<button className="button primary" type="button" onClick={() => { setTab("Worlds"); document.getElementById("world-name")?.focus(); }}><Plus size={15} />New world</button>}
      />
      <div className="subnav" role="tablist" aria-label="Control plane sections">
        {TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={tab === item ? "selected" : ""} onClick={() => setTab(item)}>{item}</button>)}
      </div>
      <div className="control-layout">
        <Panel title={tab} meta={<span>{selectedWorld?.name ?? "No active world"}</span>} className="control-primary">
          {actionError ? <p className="field-error action-feedback" role="alert">{actionError}</p> : null}
          {actionStatus ? <p className="action-status action-feedback" role="status">{actionStatus}</p> : null}
          {tab === "Worlds" ? (
            <>
              <form className="inline-create" onSubmit={submitWorld}>
                <label htmlFor="world-name">World name</label>
                <input id="world-name" data-testid="world-name" value={worldName} onChange={(event) => setWorldName(event.target.value)} placeholder="e.g. New Briar 1699" />
                <button className="button primary" type="submit" disabled={!worldName.trim() || busy}><Plus size={15} />{workingAction.startsWith("World") ? "Creating…" : "Create world"}</button>
              </form>
              <WorldsTable worlds={worlds} />
            </>
          ) : tab === "Runs" ? (
            <><RunCreateForm worldId={activeWorldId} busy={busy} execute={execute} /><RunsTable runs={payload.runs} /></>
          ) : tab === "Actors & Capabilities" ? (
            <><ActorCreateForm worldId={activeWorldId} busy={busy} execute={execute} /><ActorsTable actors={payload.actors} /></>
          ) : tab === "Entities" ? (
            <><EntityCreateForm worldId={activeWorldId} actors={payload.actors} busy={busy} execute={execute} /><EntitiesTable entities={payload.entities} /></>
          ) : tab === "Snapshots" ? (
            <><SnapshotCreateForm worldId={activeWorldId} busy={busy} execute={execute} /><SnapshotsTable snapshots={payload.snapshots} /></>
          ) : (
            <><BranchCreateForm worldId={activeWorldId} snapshots={payload.snapshots} busy={busy} execute={execute} /><BranchesTable branches={payload.branches} /></>
          )}
        </Panel>
        <aside className="control-inspector">
          <Panel title="World summary">
            {selectedWorld ? <DefinitionList items={[["World", selectedWorld.name], ["Status", <Status value={selectedWorld.status} />], ["Actors", payload.actors.length], ["Entities", payload.entities.length], ["Runs", payload.runs.length], ["Snapshots", payload.snapshots.length]]} /> : <EmptyState title="No world selected" detail="Create or select a world." />}
          </Panel>
          <div className="mini-stats"><Stat label="Canonical" value={payload.branches.filter((branch) => branch.kind === "CANONICAL").length} /><Stat label="Trial branches" value={payload.branches.filter((branch) => branch.kind === "TRIAL").length} /></div>
          <Panel title="Constitutional boundary">
            <ul className="icon-list"><li><Shield size={15} />Deny-by-default capabilities</li><li><GitBranch size={15} />Trial branches cannot commit canonical state</li><li><Save size={15} />Snapshots retain content hashes</li></ul>
          </Panel>
        </aside>
      </div>
    </div>
  );
}

function ActorCreateForm({ worldId, busy, execute }: { worldId: string; busy: boolean; execute: ExecuteAction }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<ActorSummary["kind"]>("AGENT");
  const [roles, setRoles] = useState("NPC");
  const [capabilities, setCapabilities] = useState("world.read, action.propose, entity.control");
  return (
    <form className="management-form" onSubmit={(event) => {
      event.preventDefault();
      const displayName = name.trim();
      if (!displayName) return;
      void execute(`Actor “${displayName}”`, () => createActor(worldId, {
        display_name: displayName,
        kind,
        roles: csv(roles),
        capabilities: csv(capabilities),
      }));
    }}>
      <label>Display name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Harbor Guide" /></label>
      <label>Kind<select value={kind} onChange={(event) => setKind(event.target.value as ActorSummary["kind"])}><option>HUMAN</option><option>AGENT</option><option>SYSTEM</option></select></label>
      <label>Roles<input value={roles} onChange={(event) => setRoles(event.target.value)} aria-describedby="actor-csv-note" /></label>
      <label>Capabilities<input value={capabilities} onChange={(event) => setCapabilities(event.target.value)} aria-describedby="actor-csv-note" /></label>
      <button className="button primary" type="submit" disabled={busy || !worldId || !name.trim()}><Plus size={15} />Create actor</button>
      <small id="actor-csv-note" className="management-note">Roles and capabilities are comma-separated and remain deny-by-default.</small>
    </form>
  );
}

function EntityCreateForm({ worldId, actors, busy, execute }: { worldId: string; actors: ActorSummary[]; busy: boolean; execute: ExecuteAction }) {
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState("NPC");
  const [controllerId, setControllerId] = useState("");
  const [x, setX] = useState(0);
  const [y, setY] = useState(0);
  return (
    <form className="management-form" onSubmit={(event) => {
      event.preventDefault();
      const entityName = name.trim();
      if (!entityName) return;
      void execute(`Entity “${entityName}”`, () => createEntity(worldId, {
        name: entityName,
        entity_type: entityType.trim() || "NPC",
        controller_actor_id: controllerId || undefined,
        x,
        y,
      }));
    }}>
      <label>Entity name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Quartermaster Ilyra" /></label>
      <label>Entity type<input value={entityType} onChange={(event) => setEntityType(event.target.value)} /></label>
      <label>Controller<select value={controllerId} onChange={(event) => setControllerId(event.target.value)}><option value="">Uncontrolled</option>{actors.map((actor) => <option key={actor.actor_id} value={actor.actor_id}>{actor.display_name}</option>)}</select></label>
      <label>Grid X<input type="number" value={x} onChange={(event) => setX(Number(event.target.value))} /></label>
      <label>Grid Y<input type="number" value={y} onChange={(event) => setY(Number(event.target.value))} /></label>
      <button className="button primary" type="submit" disabled={busy || !worldId || !name.trim()}><Plus size={15} />Create entity</button>
    </form>
  );
}

function RunCreateForm({ worldId, busy, execute }: { worldId: string; busy: boolean; execute: ExecuteAction }) {
  const [kind, setKind] = useState<RunSummary["kind"]>("LIVE");
  const [seed, setSeed] = useState(101);
  return (
    <form className="management-form compact" onSubmit={(event) => {
      event.preventDefault();
      void execute(`${kind.toLowerCase()} run`, () => createRun(worldId, kind, seed));
    }}>
      <label>Run kind<select value={kind} onChange={(event) => setKind(event.target.value as RunSummary["kind"])}><option>LIVE</option><option>POPULATION</option><option>EVALUATION</option></select></label>
      <label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
      <button className="button primary" type="submit" disabled={busy || !worldId}><Plus size={15} />Start run</button>
    </form>
  );
}

function SnapshotCreateForm({ worldId, busy, execute }: { worldId: string; busy: boolean; execute: ExecuteAction }) {
  return (
    <form className="management-form compact" onSubmit={(event) => { event.preventDefault(); void execute("Canonical snapshot", () => createSnapshot(worldId)); }}>
      <p className="management-description">Capture the active world’s canonical branch as an immutable replay basis.</p>
      <button className="button primary" type="submit" disabled={busy || !worldId}><Save size={15} />Capture snapshot</button>
    </form>
  );
}

function BranchCreateForm({ worldId, snapshots, busy, execute }: { worldId: string; snapshots: SnapshotSummary[]; busy: boolean; execute: ExecuteAction }) {
  const [snapshotId, setSnapshotId] = useState("");
  const [seed, setSeed] = useState(101);
  const selectedSnapshot = snapshotId || snapshots[0]?.snapshot_id || "";
  return (
    <form className="management-form compact" onSubmit={(event) => {
      event.preventDefault();
      if (!selectedSnapshot) return;
      void execute("Trial branch", () => createTrialBranch(worldId, selectedSnapshot, seed));
    }}>
      <label>Base snapshot<select value={selectedSnapshot} onChange={(event) => setSnapshotId(event.target.value)} disabled={!snapshots.length}>{snapshots.map((snapshot) => <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>{snapshot.name}</option>)}</select></label>
      <label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label>
      <button className="button primary" type="submit" disabled={busy || !worldId || !selectedSnapshot}><GitBranch size={15} />Create trial branch</button>
    </form>
  );
}

function WorldsTable({ worlds }: { worlds: WorldSummary[] }) {
  return <div className="data-table-wrap" data-testid="world-list"><table><thead><tr><th>World</th><th>Status</th><th>Current run</th><th>Updated</th></tr></thead><tbody>{worlds.map((world) => <tr key={world.world_id}><td><strong>{world.name}</strong><small className="mono block">{world.world_id}</small></td><td><Status value={world.status} /></td><td className="mono">{world.current_run_id?.slice(0, 13) ?? "—"}</td><td>{formatDate(world.updated_at)}</td></tr>)}</tbody></table></div>;
}

function RunsTable({ runs }: { runs: RunSummary[] }) { return runs.length ? <div className="data-table-wrap"><table><thead><tr><th>Run</th><th>Kind</th><th>Status</th><th>Duration</th></tr></thead><tbody>{runs.map((run) => <tr key={run.run_id}><td><strong>{run.name}</strong><small className="mono block">{run.run_id.slice(0, 18)}</small></td><td>{run.kind}</td><td><Status value={run.status} /></td><td>{run.duration ?? "—"}</td></tr>)}</tbody></table></div> : <EmptyState title="No runs" detail="Start a live, population, or evaluation run." />; }
function ActorsTable({ actors }: { actors: ActorSummary[] }) { return actors.length ? <div className="stack-list">{actors.map((actor) => <article className="stack-row" key={actor.actor_id}><span className="row-icon"><Users size={16} /></span><div><strong>{actor.display_name}</strong><small>{actor.kind} · {actor.roles.join(", ") || "No roles"}</small></div><div className="tag-list">{actor.capabilities.map((capability) => <span key={capability}>{capability}</span>)}</div></article>)}</div> : <EmptyState title="No actors" detail="Create an actor with explicit world-scoped authority." />; }
function EntitiesTable({ entities }: { entities: EntitySummary[] }) { return entities.length ? <div className="data-table-wrap"><table><thead><tr><th>Entity</th><th>Type</th><th>Location</th><th>Status</th></tr></thead><tbody>{entities.map((entity) => <tr key={entity.entity_id}><td><Box size={14} className="table-icon" />{entity.name}</td><td>{entity.entity_type}</td><td>{entity.location ?? "—"}</td><td><Status value={entity.status ?? "UNKNOWN"} /></td></tr>)}</tbody></table></div> : <EmptyState title="No entities" detail="Create an embodied entity at a canonical grid position." />; }
function SnapshotsTable({ snapshots }: { snapshots: SnapshotSummary[] }) { return snapshots.length ? <div className="data-table-wrap"><table><thead><tr><th>Snapshot</th><th>Event sequence</th><th>State hash</th><th>Created</th></tr></thead><tbody>{snapshots.map((snapshot) => <tr key={snapshot.snapshot_id}><td>{snapshot.name}</td><td>{snapshot.event_sequence}</td><td className="mono">{snapshot.state_hash}</td><td>{formatDate(snapshot.created_at)}</td></tr>)}</tbody></table></div> : <EmptyState title="No snapshots" detail="Capture immutable world state before branching." />; }
function BranchesTable({ branches }: { branches: BranchSummary[] }) { return branches.length ? <div className="data-table-wrap"><table><thead><tr><th>Branch</th><th>Kind</th><th>Status</th><th>Base snapshot</th></tr></thead><tbody>{branches.map((branch) => <tr key={branch.branch_id}><td><GitBranch size={14} className="table-icon" />{branch.name}</td><td>{branch.kind}</td><td><Status value={branch.status} /></td><td className="mono">{branch.base_snapshot_id ?? "—"}</td></tr>)}</tbody></table></div> : <EmptyState title="No branches" detail="Create a trial branch from a canonical snapshot." />; }
function csv(value: string) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function formatDate(value?: string) { return value ? new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—"; }
