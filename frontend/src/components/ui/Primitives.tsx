import type { ReactNode } from "react";

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1><p>{description}</p></div>{actions ? <div className="page-actions">{actions}</div> : null}</header>;
}

export function Panel({ title, meta, children, className = "" }: { title: string; meta?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`.trim()}><div className="panel-heading"><h2>{title}</h2>{meta ? <div className="panel-meta">{meta}</div> : null}</div>{children}</section>;
}

export function Status({ value }: { value: string }) {
  const tone = /active|running|ready|complete|valid|verified|approved/i.test(value) ? "ok" : /error|failed|stopped|invalid|denied/i.test(value) ? "bad" : /warn|review|draft|paused|queued/i.test(value) ? "warn" : "neutral";
  return <span className={`status ${tone}`}><i aria-hidden="true" />{value.replaceAll("_", " ")}</span>;
}

export function Stat({ label, value, detail }: { label: string; value: ReactNode; detail?: string }) {
  return <div className="stat"><span>{label}</span><strong>{value}</strong>{detail ? <small>{detail}</small> : null}</div>;
}

export function DefinitionList({ items }: { items: Array<[string, ReactNode]> }) {
  return <dl className="definition-list">{items.flatMap(([label, value]) => [<dt key={`${label}-dt`}>{label}</dt>, <dd key={`${label}-dd`}>{value}</dd>])}</dl>;
}
