import type { EventRecord } from "../../core/api/types";

function humanize(value: string): string {
  const words = value.replaceAll("_", " ").replaceAll("-", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function eventSummary(event: EventRecord): string {
  if (event.summary?.trim()) return event.summary.trim();
  const eventLabel = humanize(event.event_type.split(".").at(-1) ?? event.event_type);
  const payload = event.payload ?? {};
  for (const key of ["summary", "message", "description", "narration"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  const details = Object.entries(payload)
    .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 3)
    .map(([key, value]) => `${humanize(key)}: ${humanize(String(value))}`);
  return details.length ? `${eventLabel} · ${details.join(" · ")}` : eventLabel;
}

export function eventActor(event: EventRecord): string {
  return event.actor_name?.trim() || event.actor_id || "system";
}
