import { useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Map, MessageSquare, RefreshCw, Send, Swords } from "lucide-react";
import { useAppContext } from "../../app/AppContext";
import { DefinitionList, PageHeader, Panel, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { EntitySummary } from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { loadGameState, proposeCommand, type CommandAcknowledgement } from "./api";
import { entityMapPosition } from "./mapPosition";
import { uniqueObservations } from "./sceneRefresh";

const MAP_URL = `${import.meta.env.BASE_URL}assets/harborport-map.png`;

export default function GameConsolePage() {
  const { activeWorldId } = useAppContext();
  return <WorldConsole key={activeWorldId} activeWorldId={activeWorldId} />;
}

function WorldConsole({ activeWorldId }: { activeWorldId: string }) {
  const [selectedEntityId, setSelectedEntityId] = useState("");
  return <SceneConsole key={selectedEntityId} activeWorldId={activeWorldId}
    selectedEntityId={selectedEntityId} onViewpointChange={setSelectedEntityId} />;
}

function SceneConsole({ activeWorldId, selectedEntityId, onViewpointChange }: {
  activeWorldId: string; selectedEntityId: string; onViewpointChange: (entityId: string) => void;
}) {
  const [accepted, setAccepted] = useState<CommandAcknowledgement | null>(null);
  const readController = useRef<AbortController | null>(null);
  const scopeEpoch = useRef(0);
  const commandInput = useRef<HTMLTextAreaElement | null>(null);
  const refreshButton = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef<"command" | "refresh" | null>(null);
  const resource = useAsyncResource(
    () => {
      readController.current?.abort();
      const controller = new AbortController();
      readController.current = controller;
      if (accepted && !accepted.scene_refresh) {
        return Promise.reject(new Error("The server did not provide scene refresh status. Reload this page to read the scene."));
      }
      return loadGameState(activeWorldId, selectedEntityId, accepted?.scene_refresh ?? undefined, controller.signal);
    },
    [activeWorldId, selectedEntityId, accepted?.event_id],
  );
  useEffect(() => () => {
    scopeEpoch.current += 1;
    readController.current?.abort();
  }, []);
  useEffect(() => {
    if (resource.loading || resource.error || !restoreFocus.current) return;
    const target = restoreFocus.current === "command" ? commandInput.current : refreshButton.current;
    target?.focus();
    restoreFocus.current = null;
  }, [resource.loading, resource.error]);
  const [focusedEntityId, setFocusedEntityId] = useState("");
  const [command, setCommand] = useState("");
  const [sending, setSending] = useState(false);
  const [commandError, setCommandError] = useState("");
  const game = resource.data?.data;
  const selectedViewpointId = selectedEntityId || game?.observer_entity_id || "";
  const selectedViewpoint = game?.viewpoints?.find((item) => item.entity_id === selectedViewpointId);
  const canAct = Boolean(selectedViewpoint) && selectedViewpoint?.can_act !== false && resource.data?.source === "live";
  const selected = game?.entities.find((entity) => entity.entity_id === focusedEntityId)
    ?? game?.entities.find((entity) => entity.entity_id === selectedViewpointId)
    ?? game?.entities[0]
    ?? null;
  const events = useMemo(() => uniqueObservations(game?.events ?? []), [game?.events]);

  async function submitCommand(event: React.FormEvent) {
    event.preventDefault();
    const text = command.trim();
    if (!text || !game || !canAct || sending) return;
    const submittedScope = scopeEpoch.current;
    setSending(true);
    setCommandError("");
    try {
      const result = await proposeCommand(activeWorldId, text, game, selectedViewpointId || undefined);
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
  if (resource.error) return <ErrorState message={accepted ? `Action was accepted. ${resource.error} Retry the scene refresh; do not resend the action.` : resource.error} retry={resource.reload} />;
  if (!game) return <EmptyState title="No world state" detail="Create a world and start a live run in Control Plane." />;

  return (
    <div className="page game-page">
      <SourceNotice source={resource.data?.source ?? "live"} reason={resource.data?.reason} />
      <PageHeader
        title="Game Console"
        description="See and hear only what the selected embodied character can perceive, then submit typed proposals."
        actions={<><Status value={game.interaction_status} /><button ref={refreshButton} className="button" type="button" onClick={() => { restoreFocus.current = "refresh"; resource.reload(); }}><RefreshCw size={15} />Refresh</button></>}
      />
      <div className="game-grid">
        <Panel title="Perceived Harborport" meta={<span>Projection {game.projection_version ?? "—"}</span>} className="map-panel">
          <div className="map-stage" aria-label="Perception-scoped tactical map of Harborport">
            <img src={MAP_URL} alt="Top-down map of Harborport docks and market" />
            {game.entities.slice(0, 4).map((entity) => (
              <button
                className={`map-token ${entity.entity_id === selected?.entity_id ? "selected" : ""} ${entity.detail_level?.toLowerCase() ?? ""}`}
                key={entity.entity_id}
                style={entityMapPosition(entity)}
                type="button"
                aria-label={`Inspect ${entity.name} on map`}
                onClick={() => setFocusedEntityId(entity.entity_id)}
              >{entity.name.slice(0, 1)}</button>
            ))}
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
            <label>Command or dialogue<textarea ref={commandInput} value={command} onChange={(event) => setCommand(event.target.value)} placeholder="/move north, /attack Dockmaster Vale, /cast …, or speak naturally" rows={4} /></label>
            {!canAct ? <p className="field-error" role="status">This viewpoint is available for inspection only. Select a body assigned to you to act.</p> : null}
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
  return (
    <button className={`selection-row ${selected ? "selected" : ""}`} type="button" role="option" aria-selected={selected} onClick={onSelect}>
      <span className="entity-sigil">{entity.detail_level === "PRESENCE" ? "•" : entity.name.slice(0, 1)}</span><span><strong>{entity.name}</strong><small>{entity.entity_type} · {entity.location ?? "Unknown"} · {entity.detail_level ?? "VISIBLE"}</small>{entity.health === undefined ? null : <i className="health-track"><b style={{ width: `${health}%` }} /></i>}</span>
    </button>
  );
}
