import { useMemo, useState } from "react";
import { Braces, CheckCircle2, Dna, Play, RefreshCw } from "lucide-react";
import { PageHeader, Panel, Status } from "../../components/ui/Primitives";
import { EmptyState, ErrorState, LoadingState, SourceNotice } from "../../components/ui/States";
import type { CompiledPersona, PersonaBlueprint, PersonaDimension } from "../../core/api/types";
import { useAsyncResource } from "../../core/hooks/useAsyncResource";
import { compilePersona, generatePersona, loadPersonaStudio } from "./api";

const PACKS = ["core", "world", "tabletop", "accessibility"] as const;
type Pack = typeof PACKS[number];

const PACK_HINTS: Record<Pack, string[]> = {
  core: ["decision", "risk", "trust", "curiosity", "communication", "personality", "value", "bias", "habit", "social"],
  world: ["region", "culture", "class", "occupation", "religion", "education", "faction", "species"],
  tabletop: ["rules", "play", "combat", "exploration", "roleplay", "metagaming", "completion", "dm_"],
  accessibility: ["reading", "visual", "motor", "cognitive", "interface", "access"],
};

function inferPack(spec: PersonaDimension): Pack {
  if (PACKS.includes(spec.pack as Pack)) return spec.pack as Pack;
  return PACKS.find((pack) => PACK_HINTS[pack].some((hint) => spec.name.includes(hint))) ?? "core";
}

export default function PersonaStudioPage() {
  const resource = useAsyncResource(loadPersonaStudio, []);
  const [pack, setPack] = useState<Pack>("core");
  const [seed, setSeed] = useState(4815162342);
  const [fixed, setFixed] = useState<Record<string, unknown>>({});
  const [persona, setPersona] = useState<PersonaBlueprint | null>(null);
  const [compiled, setCompiled] = useState<CompiledPersona | null>(null);
  const [working, setWorking] = useState(false);
  const [actionError, setActionError] = useState("");
  const schema = resource.data?.data.schema;
  const dimensions = useMemo(() => schema?.dimensions.filter((spec) => inferPack(spec) === pack) ?? [], [schema, pack]);

  async function runGeneration() {
    setWorking(true);
    setActionError("");
    setCompiled(null);
    try {
      const result = await generatePersona(seed, fixed);
      setPersona(result.data);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Persona generation failed");
    } finally {
      setWorking(false);
    }
  }

  async function runCompilation() {
    if (!persona) return;
    setWorking(true);
    setActionError("");
    try {
      const result = await compilePersona(persona);
      setCompiled(result.data);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Persona compilation failed");
    } finally {
      setWorking(false);
    }
  }

  if (resource.loading) return <LoadingState label="Loading persona schema" />;
  if (resource.error) return <ErrorState message={resource.error} retry={resource.reload} />;
  if (!schema) return <EmptyState title="No persona schema" detail="Install or register a versioned persona schema." />;

  return (
    <div className="page persona-page">
      <SourceNotice source={resource.data?.source ?? "live"} reason={resource.data?.reason} />
      <PageHeader title="Persona Studio" description="Generate reproducible identities, validate dependencies, and inspect compiled behavior." actions={<><label className="seed-control" htmlFor="persona-seed">Seed<input id="persona-seed" data-testid="persona-seed" type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label><button className="button primary" type="button" onClick={runGeneration} disabled={working}><Dna size={15} />{working ? "Working…" : "Generate persona"}</button></>} />
      <div className="persona-layout">
        <Panel title="Dimensions" meta={<span>{schema.dimensions.length} registered · schema {schema.version}</span>} className="dimension-panel">
          <div className="subnav inner" role="tablist" aria-label="Persona schema packs">{PACKS.map((item) => <button key={item} type="button" role="tab" aria-selected={pack === item} className={pack === item ? "selected" : ""} onClick={() => setPack(item)}>{item}</button>)}</div>
          <div className="dimension-table">
            <div className="dimension-row header"><span>Dimension</span><span>Fixed assignment</span><span>Dependency</span></div>
            {dimensions.map((spec) => <DimensionEditor key={spec.name} spec={spec} value={fixed[spec.name]} onChange={(value) => setFixed((current) => value === undefined ? Object.fromEntries(Object.entries(current).filter(([name]) => name !== spec.name)) : { ...current, [spec.name]: value })} />)}
          </div>
        </Panel>
        <aside className="persona-inspector">
          <Panel title="Validation" meta={persona ? <Status value={persona.validation.status} /> : <span>Awaiting generation</span>}>
            {!persona ? <EmptyState title="No generated persona" detail="Choose fixed assignments or use the seeded defaults." /> : <div data-testid="persona-validation"><p className="validation-line"><CheckCircle2 size={17} />{persona.validation.errors.length ? `${persona.validation.errors.length} constraint errors` : "Dependency graph and values are valid."}</p>{persona.validation.errors.map((error) => <p className="field-error" key={error}>{error}</p>)}<dl className="definition-list"><dt>Persona ID</dt><dd className="mono">{persona.persona_id}</dd><dt>Generator</dt><dd>{persona.generator_version}</dd><dt>Ruleset</dt><dd>{persona.validation.ruleset_version}</dd><dt>Seed</dt><dd className="mono">{persona.seed}</dd></dl></div>}
          </Panel>
          <Panel title="Compiler preview" meta={compiled ? <Status value="COMPILED" /> : undefined}>
            {!persona ? <EmptyState title="Compile after generation" detail="The compiler maps identity into policy weights and retrieval filters." /> : !compiled ? <button className="button wide" type="button" onClick={runCompilation} disabled={working}><Play size={15} />Compile persona</button> : <div className="compiler-preview" data-testid="persona-result"><p>{compiled.identity_summary}</p><h3>Policy weights</h3>{Object.entries(compiled.policy_weights).map(([name, value]) => <div className="factor" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{value.toFixed(2)}</strong></div>)}<h3>Starting goals</h3><ul>{compiled.starting_goals.map((goal) => <li key={goal}>{goal}</li>)}</ul><small className="mono">{compiled.compiler_version}</small></div>}
          </Panel>
          <Panel title="Saved profiles" meta={<button className="icon-button" type="button" aria-label="Refresh personas" onClick={resource.reload}><RefreshCw size={14} /></button>}>
            <div className="saved-personas">{resource.data?.data.personas.map((item) => <button type="button" key={item.persona_id} onClick={() => { setPersona(item); setSeed(item.seed); setFixed({}); setCompiled(null); }}><Braces size={15} /><span><strong>{item.persona_id.slice(0, 18)}</strong><small>seed {item.seed} · {item.validation.status}</small></span></button>)}</div>
          </Panel>
        </aside>
      </div>
      {actionError ? <div className="toast error" role="alert">{actionError}</div> : null}
    </div>
  );
}

function DimensionEditor({ spec, value, onChange }: { spec: PersonaDimension; value: unknown; onChange: (value: unknown | undefined) => void }) {
  const dependency = Object.keys(spec.depends_on ?? {}).join(", ") || "—";
  return (
    <div className="dimension-row">
      <span><strong>{spec.name.replaceAll("_", " ")}</strong><small>{spec.kind}</small></span>
      <span>{spec.kind === "enum" ? <select aria-label={`Fixed ${spec.name}`} value={value === undefined ? "" : String(value)} onChange={(event) => onChange(event.target.value || undefined)}><option value="">Seeded</option>{spec.values?.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select> : spec.kind === "boolean" ? <select aria-label={`Fixed ${spec.name}`} value={value === undefined ? "" : String(value)} onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "true")}><option value="">Seeded</option><option value="true">True</option><option value="false">False</option></select> : <input aria-label={`Fixed ${spec.name}`} type="number" min={spec.minimum ?? undefined} max={spec.maximum ?? undefined} value={value === undefined ? "" : Number(value)} placeholder="Seeded" onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))} />}</span>
      <span className="muted">{dependency}</span>
    </div>
  );
}
