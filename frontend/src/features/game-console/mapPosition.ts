import type { CSSProperties } from "react";
import type { EntitySummary } from "../../core/api/types";

const MAP_ORIGIN_PERCENT = 12;
const MAP_CELL_PERCENT = 15;
const MAP_EDGE_PERCENT = 8;

function coordinate(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function position(value: unknown): string {
  const percent = MAP_ORIGIN_PERCENT + coordinate(value) * MAP_CELL_PERCENT;
  return `${Math.max(MAP_EDGE_PERCENT, Math.min(100 - MAP_EDGE_PERCENT, percent))}%`;
}

export function entityMapPosition(entity: Pick<EntitySummary, "public_state">): CSSProperties {
  return {
    left: position(entity.public_state?.x),
    top: position(entity.public_state?.y),
  };
}
