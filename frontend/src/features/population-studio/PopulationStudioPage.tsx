import { useMemo, useState } from "react";
import { DatabaseZap, Filter, Play, Users } from "lucide-react";
import { useAppContext } from "../../app/AppContext";
import { PageHeader, Panel, Stat, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { CohortMember, PopulationDefinition } from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { activatePopulation, generatePopulation, loadPopulations, materializePopulation, samplePopulation } from "./api";

export default function PopulationStudioPage() {
  const { activeWorldId } = useAppContext();
  const resource = useAsyncResource(() => loadPopulations(activeWorldId), [activeWorldId]);
  const [localDefinitions, setLocalDefinitions] = useState<PopulationDefinition[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("Harborport Working Set");
  const [size, setSize] = useState(1000);
  const [seed, setSeed] = useState(1831);
  const [perCell, setPerCell] = useState(2);
  const [cohort, setCohort] = useState<CohortMember[]>([]);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const definitions = useMemo(() => [
    ...(resource.data?.data ?? []),
    ...localDefinitions.filter((item) => item.world_id === activeWorldId),
  ], [activeWorldId, resource.data?.data, localDefinitions]);
  const selected = definitions.find((item) => item.population_id === selectedId) ?? definitions[0] ?? null;

  async function run(label: string, action: () => Promise<void>) {
    setWorking(label);
    setError("");
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : `${label} failed`); } finally { setWorking(""); }
  }

  if (resource.loading) return <LoadingState label="Opening population warehouse" />;
  if (resource.error) return <ErrorState message={resource.error} retry={resource.reload} />;

  return (
    <div className="page population-page">
      <SourceNotice source={resource.data?.source ?? "live"} reason={resource.data?.reason} />
      <PageHeader title="Population Studio" description="Define statistical populations, fill strata deliberately, and activate only what the world needs." actions={<button className="button primary" type="button" onClick={() => run("generate", async () => { const result = await generatePopulation({ name, size, seed, world_id: activeWorldId }); setLocalDefinitions((items) => [...items, result.data]); setSelectedId(result.data.population_id); })} disabled={Boolean(working) || !activeWorldId}><DatabaseZap size={15} />{working === "generate" ? "Generating…" : "Generate population"}</button>} />
      <div className="population-layout">
        <Panel title="Population definitions" meta={<span>{definitions.length} pools</span>} className="population-list-panel">
          <form className="population-form" onSubmit={(event) => event.preventDefault()}>
            <label>Population name<input data-testid="population-name" value={name} onChange={(event) => setName(event.target.value)} /></label>
            <div className="form-pair"><label>Size<input data-testid="population-size" type="number" min={1} max={5000000} value={size} onChange={(event) => setSize(Number(event.target.value))} /></label><label>Seed<input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label></div>
          </form>
          <div className="selection-list" role="listbox" aria-label="Population definitions">{definitions.map((definition) => <button className={`selection-row ${definition.population_id === selected?.population_id ? "selected" : ""}`} type="button" role="option" aria-selected={definition.population_id === selected?.population_id} key={definition.population_id} onClick={() => { setSelectedId(definition.population_id); setCohort([]); }}><span className="entity-sigil"><Users size={16} /></span><span><strong>{definition.name}</strong><small>{definition.size.toLocaleString()} profiles · seed {definition.seed}</small></span><Status value={definition.status} /></button>)}</div>
        </Panel>
        <Panel title="Strata matrix" meta={selected ? <span>{selected.name}</span> : undefined} className="strata-panel">
          {!selected ? <EmptyState title="No population" detail="Generate a pool to inspect its declared distributions." /> : <><div className="stat-strip"><Stat label="Statistical" value={selected.size.toLocaleString()} /><Stat label="Materialized" value={selected.materialized.toLocaleString()} /><Stat label="Active" value={selected.active.toLocaleString()} /></div><StrataMatrix population={selected} /><div className="population-actions"><label>Per stratum<input type="number" min={1} max={100} value={perCell} onChange={(event) => setPerCell(Number(event.target.value))} /></label><button className="button" type="button" disabled={Boolean(working)} onClick={() => run("sample", async () => { const result = await samplePopulation(selected.population_id, perCell); setCohort(result.data); })}><Filter size={15} />{working === "sample" ? "Sampling…" : "Sample cohort"}</button><button className="button" type="button" disabled={Boolean(working) || !activeWorldId} onClick={() => run("materialize", async () => { const result = await materializePopulation(selected.population_id, 24, activeWorldId); selected.materialized = result.data.materialized; setLocalDefinitions((items) => [...items]); })}>Materialize 24</button><button className="button primary" type="button" disabled={Boolean(working) || !activeWorldId} onClick={() => run("activate", async () => { const result = await activatePopulation(selected.population_id, 8, activeWorldId); selected.active = result.data.active; setLocalDefinitions((items) => [...items]); })}><Play size={15} />Activate 8</button></div></>}
        </Panel>
        <Panel title="Cohort result" meta={<span>{cohort.length} sampled profiles</span>} className="cohort-panel" >
          {cohort.length ? <div className="data-table-wrap" data-testid="cohort-results"><table><thead><tr><th>Persona</th><th>Seed</th><th>Occupation sector</th><th>Risk</th><th>Rules</th></tr></thead><tbody>{cohort.map((member) => <tr key={member.persona_id}><td className="mono">{member.persona_id.slice(0, 20)}</td><td>{member.seed}</td><td>{String(member.dimensions.occupation_sector ?? "—")}</td><td>{String(member.dimensions.risk_tolerance ?? "—")}</td><td>{String(member.dimensions.rules_familiarity ?? "—")}</td></tr>)}</tbody></table></div> : <EmptyState title="No cohort sampled" detail="Choose a population and sample across occupation sector × risk strata." />}
        </Panel>
      </div>
      {error ? <div className="toast error" role="alert">{error}</div> : null}
    </div>
  );
}

function StrataMatrix({ population }: { population: PopulationDefinition }) {
  const dimensions = population.dimensions ?? {};
  const [firstName, firstValues] = Object.entries(dimensions)[0] ?? ["distribution", {}];
  const max = Math.max(1, ...Object.values(firstValues));
  return <div className="strata-matrix"><h3>{firstName.replaceAll("_", " ")}</h3>{Object.entries(firstValues).map(([name, count]) => <div className="strata-row" key={name}><span>{name.replaceAll("_", " ")}</span><i><b style={{ width: `${count / max * 100}%` }} /></i><strong>{count.toLocaleString()}</strong></div>)}</div>;
}
