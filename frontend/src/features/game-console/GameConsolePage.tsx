import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Map, MessageSquare, RefreshCw, Send, Swords } from "lucide-react";
import { useAppContext } from "../../app/AppContext";
import { DefinitionList, PageHeader, Panel, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { EntitySummary } from "../../core/api/types";
import { proposeCommand, type CommandAcknowledgement, type ControlMode } from "./api";
import ControlPanel from "./ControlPanel";
import { entityMapPosition, mapLayout } from "./mapPosition";
import { uniqueObservations } from "./sceneRefresh";
import { useConsoleScene } from "./useConsoleScene";

export default function GameConsolePage() {
  const { activeWorldId } = useAppContext();
  return <WorldConsole key={activeWorldId} activeWorldId={activeWorldId} />;
}

function WorldConsole({ activeWorldId }: { activeWorldId: string }) {
  const [selectedEntityId, setSelectedEntityId] = useState("");
  const [selectionEpoch, setSelectionEpoch] = useState(0);
  function choose(entityId: string) { setSelectedEntityId(entityId); setSelectionEpoch(value => value + 1); }
  return <SceneConsole key={`${selectedEntityId}:${selectionEpoch}`} activeWorldId={activeWorldId}
    selectedEntityId={selectedEntityId} onViewpointChange={choose} />;
}

function SceneConsole({ activeWorldId, selectedEntityId, onViewpointChange }: {
  activeWorldId: string; selectedEntityId: string; onViewpointChange: (entityId: string) => void;
}) {
  const [accepted, setAccepted] = useState<CommandAcknowledgement | null>(null);
  const scopeEpoch = useRef(0);
  const commandInput = useRef<HTMLTextAreaElement | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef<"command" | "refresh" | null>(null);
  const resource = useConsoleScene(activeWorldId, selectedEntityId, accepted);
  useEffect(() => () => {
    scopeEpoch.current += 1;
  }, []);
  useEffect(() => {
    if (resource.loading || resource.error || !restoreFocus.current) return;
    const target = restoreFocus.current === "command" ? commandInput.current : refreshButton.current;
    target?.focus();
    restoreFocus.current = null;
  }, [resource.loading, resource.error, resource.data]);
  const [focusedEntityId, setFocusedEntityId] = useState("");
  const [mapZone, setMapZone] = useState("");
  const [command, setCommand] = useState("");
  const [sending, setSending] = useState(false);
  const [commandError, setCommandError] = useState("");
  const [controlMode, setControlMode] = useState<ControlMode | "UNAVAILABLE">("HUMAN");
  const [controlEpoch, setControlEpoch] = useState<number | undefined>();
  const previousStep = useRef<number | null>(null);
  const updateController = useCallback((mode: ControlMode | "UNAVAILABLE", epoch?: number) => {
    setControlMode(mode); setControlEpoch(epoch);
  }, []);
  const reloadScene = resource.reload;
  const refreshProgress = useCallback((step: number) => {
    const changed = previousStep.current !== null && previousStep.current !== step;
    previousStep.current = step;
    if (changed) reloadScene();
  }, [reloadScene]);
  const game = resource.data?.data;
  const selectedViewpointId = selectedEntityId || game?.observer_entity_id || "";
  const selectedViewpoint = game?.viewpoints?.find((item) => item.entity_id === selectedViewpointId);
  const ownedViewpoint = Boolean(selectedViewpoint) && selectedViewpoint?.can_act !== false && resource.data?.source === "live";
  const canAct = ownedViewpoint && Boolean(game?.run) && controlMode === "HUMAN" && !resource.syncError && game?.experience_ready !== false;
  const selected = game?.entities.find((entity) => entity.entity_id === focusedEntityId)
    ?? game?.entities.find((entity) => entity.entity_id === selectedViewpointId)
    ?? game?.entities[0]
    ?? null;
  const events = useMemo(() => uniqueObservations(game?.events ?? []), [game?.events]);
  const zones = Array.from(new Set((game?.entities ?? []).flatMap(entity =>
    entity.public_state ? [String(entity.public_state.zone_id ?? "world")] : []))).sort();
  const ownZone = String(game?.entities.find(entity => entity.entity_id === selectedViewpointId)?.public_state?.zone_id ?? "world");
  const zone = zones.includes(mapZone) ? mapZone : zones.includes(ownZone) ? ownZone : zones[0] ?? "world";
  const mapEntities = (game?.entities ?? []).filter(entity => entity.public_state && String(entity.public_state.zone_id ?? "world") === zone);
  const presentation = game?.map_presentations?.find(item => item.zone_id === zone);
  const layout = mapLayout(mapEntities, presentation);

  async function submitCommand(event: React.FormEvent) {
    event.preventDefault();
    const text = command.trim();
    if (!text || !game || !canAct || sending) return;
    const submittedScope = scopeEpoch.current;
    setSending(true);
    setCommandError("");
    try {
      const result = await proposeCommand(activeWorldId, text, game, selectedViewpointId || undefined, controlEpoch);
      if (submittedScope !== scopeEpoch.current) return;
      setAccepted(result.data);
      setCommand("");
      restoreFocus.current = "command";
      resource.reload();
    } catch (error) {
      if (submittedScope !== scopeEpoch.current) return;
      setCommandError(error instanceof Error ? error.message : "Command proposal failed");
    } finally {
      if (submittedScope === scopeEpoch.current) setSending(false);
    }
  }

  if (resource.loading) return <LoadingState label={accepted ? "Action accepted. Updating your scene…" : "Loading live world"} />;
  if (resource.error) return <div><ErrorState message={accepted ? `Action was accepted. ${resource.error} Retry the scene refresh; do not resend the action.` : resource.error} retry={resource.reload} /><button className="button" type="button" onClick={() => onViewpointChange("")}>Choose assigned character</button></div>;
  if (!game) return <EmptyState title="No world state" detail="Create a world and start a live run in Control Plane." />;

  return (
    <div className="page game-page">
      <SourceNotice source={resource.data?.source ?? "live"} reason={resource.data?.reason} />
      {resource.syncError ? <div role="status" className="field-error">{resource.syncError} <button className="button" type="button" onClick={() => onViewpointChange("")}>Choose assigned character</button></div> : null}
      <PageHeader
        title="Game Console"
        description="See and hear only what the selected embodied character can perceive, then submit typed proposals."
        actions={<><Status value={game.interaction_status} /><button ref={refreshButton} className="button" type="button" onClick={() => { restoreFocus.current = "refresh"; resource.reload(); }}><RefreshCw size={15} />Refresh</button></>}
      />
      {ownedViewpoint && game.branch && game.run ? <ControlPanel
        key={`${game.branch.branch_id}:${game.run.run_id}:${selectedViewpointId}`}
        scope={{ world: activeWorldId, branch: game.branch.branch_id, run: game.run.run_id, entity: selectedViewpointId }}
        onModeChange={updateController} onProgress={refreshProgress} /> : null}
      <div className="game-grid">
        <Panel title={`Perceived ${presentation?.name ?? zone}`} meta={<span>Projection {game.projection_version ?? "—"}</span>} className="map-panel">
          {zones.length > 1 ? <label className="map-zone">Map zone<select value={zone} onChange={event => setMapZone(event.target.value)}>{zones.map(item => <option key={item} value={item}>{game.map_presentations?.find(map => map.zone_id === item)?.name ?? item}</option>)}</select></label> : null}
          <div className={`map-stage ${layout.imagePath ? "" : "coordinate-grid"}`} style={layout.imagePath ? undefined : { backgroundSize: `${100 / (layout.bounds.max_x - layout.bounds.min_x + 1)}% ${100 / (layout.bounds.max_y - layout.bounds.min_y + 1)}%` }} aria-label={`Perception-scoped tactical map of ${presentation?.name ?? zone}`}>
            {layout.imagePath ? <img src={layout.imagePath} alt={`Map of ${presentation?.name ?? zone}`} /> : null}
            {mapEntities.map((entity) => {
              const position = entityMapPosition(entity, layout.bounds);
              return position ? (
              <button
                className={`map-token ${entity.entity_id === selected?.entity_id ? "selected" : ""} ${entity.detail_level?.toLowerCase() ?? ""}`}
                key={entity.entity_id}
                style={position}
                type="button"
                aria-label={`Inspect ${entity.name} on map`}
                onClick={() => setFocusedEntityId(entity.entity_id)}
              >{entity.name.slice(0, 1)}</button>
              ) : null;
            })}
            <span className="map-coordinates">Grid x {layout.bounds.min_x}…{layout.bounds.max_x}, y {layout.bounds.min_y}…{layout.bounds.max_y}{layout.autoScaled ? " · visible positions" : ""}</span>
          </div>
        </Panel>
        <Panel title="Perceived entities" meta={<span>{game.entities.length} perceived</span>} className="entity-panel">
          <div className="selection-list compact" role="listbox" aria-label="Perceived entities">
            {game.entities.map((entity) => <EntityRow key={entity.entity_id} entity={entity} selected={entity.entity_id === selected?.entity_id} onSelect={() => setFocusedEntityId(entity.entity_id)} />)}
          </div>
          {selected ? <div className="entity-detail"><DefinitionList items={[["Type", selected.entity_type], ["Location", selected.location ?? "Unknown"], ["Status", <Status value={selected.status ?? "UNKNOWN"} />], ["Health", selected.health === undefined ? "—" : `${selected.health} / ${selected.max_health ?? "—"}`]]} /></div> : null}
        </Panel>
        <Panel title="Observation feed" meta={<span>{events.length} perceived events</span>} className="event-panel">
          {events.length ? <div className="event-feed">{events.map((item) => <article className="event-row" key={item.event_id}><time>{new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time><span className="event-icon">{item.event_type.includes("dialogue") ? <MessageSquare size={14} /> : item.event_type.includes("movement") ? <Map size={14} /> : <Swords size={14} />}</span><div><strong>{item.actor_name ?? item.event_type}</strong><p>{item.summary}</p></div></article>)}</div> : <EmptyState title="No visible events" detail="Visible ledger events will appear here." />}
        </Panel>
        <Panel title="Command composer" meta={<span>Embodied proposal</span>} className="command-panel">
          <form className="command-form" onSubmit={submitCommand}>
            <label>Embodied viewpoint<select value={selectedViewpointId} onChange={(event) => onViewpointChange(event.target.value)}>{(game.viewpoints ?? []).map((entity) => <option key={entity.entity_id} value={entity.entity_id}>{entity.name}{entity.can_act === false ? " · inspect only" : ""}</option>)}</select></label>
            <label>Command or dialogue<textarea aria-label="Command or dialogue" ref={commandInput} value={command} onChange={(event) => setCommand(event.target.value)} placeholder="/move north, /attack Dockmaster Vale, /cast MEND Aster Vale, or speak naturally" rows={4} /></label>
            {!canAct ? <p className="field-error" role="status">{resource.syncError ? "Wait for scene synchronization before acting." : game.experience_ready === false ? "Your character's observations are updating. Wait for synchronization before acting." : !selectedViewpoint ? "No assigned character is available. Ask your DM to assign a body." : !game.run ? "Start an unfinished live run before acting." : controlMode !== "HUMAN" ? "Take control before submitting a command." : "This viewpoint is available for inspection only. Select a body assigned to you to act."}</p> : null}
            {commandError ? <p className="field-error" role="alert">{commandError}</p> : null}
            <button className="button primary" type="submit" disabled={sending || !command.trim() || !canAct}><Send size={15} />{sending ? "Proposing…" : "Send proposal"}</button>
          </form>
          <p className="constitutional-note"><Crosshair size={15} />The model or operator proposes. The kernel validates and commits.</p>
        </Panel>
      </div>
    </div>
  );
}

function EntityRow({ entity, selected, onSelect }: { entity: EntitySummary; selected: boolean; onSelect: () => void }) {
  const health = entity.health === undefined || !entity.max_health ? 0 : Math.round(entity.health / entity.max_health * 100);
  const activityNames = { WEED: "Weeding", REST: "Resting", EAT: "Eating", TRAVEL: "Traveling", SLEEP: "Sleeping", SOCIAL: "Socializing" };
  const measurable = entity.activity && ["WEED", "REST", "EAT"].includes(entity.activity.kind);
  return (
    <button className={`selection-row ${selected ? "selected" : ""}`} type="button" role="option" aria-selected={selected} onClick={onSelect}>
      <span className="entity-sigil">{entity.detail_level === "PRESENCE" ? "•" : entity.name.slice(0, 1)}</span><span><strong>{entity.name}</strong><small>{entity.entity_type} · {entity.location ?? "Unknown"} · {entity.detail_level ?? "VISIBLE"}</small>{entity.activity ? <small>{entity.activity.kind === "SOCIAL" && entity.activity.status === "WAITING" ? "Waiting" : activityNames[entity.activity.kind]} · {measurable ? `${entity.activity.progress_percent}% · ` : ""}{entity.activity.status.toLowerCase()} · work {entity.activity.weeded_units}</small> : null}{entity.health === undefined ? null : <i className="health-track"><b style={{ width: `${health}%` }} /></i>}</span>
    </button>
  );
}
