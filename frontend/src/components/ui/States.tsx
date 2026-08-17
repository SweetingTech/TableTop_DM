import { AlertTriangle, Database, LoaderCircle, RefreshCw } from "lucide-react";
import type { DataSource } from "../../core/api/types";

export function LoadingState({ label = "Loading workspace" }: { label?: string }) {
  return <div className="state-panel" role="status"><LoaderCircle className="spin" aria-hidden="true" /><span>{label}</span></div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="state-panel error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div><strong>Unable to load this instrument</strong><span>{message}</span></div>
      {retry ? <button className="button" type="button" onClick={retry}><RefreshCw size={15} aria-hidden="true" /> Retry</button> : null}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><Database aria-hidden="true" /><strong>{title}</strong><span>{detail}</span></div>;
}

export function SourceNotice({ source, reason }: { source: DataSource; reason?: string }) {
  if (source === "live") return null;
  return (
    <div className="demo-notice" role="status" data-testid="demo-mode-banner">
      <span>Deterministic demo fallback</span>
      <p>{reason ?? "A live endpoint is unavailable. Data on this screen is an explicit local fixture."}</p>
    </div>
  );
}
