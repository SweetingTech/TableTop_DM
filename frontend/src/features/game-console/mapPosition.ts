import type { CSSProperties } from "react";
import type { EntitySummary, MapPresentation } from "../../core/api/types";

export type GridBounds = Pick<MapPresentation, "min_x" | "max_x" | "min_y" | "max_y">;
type Positioned = Pick<EntitySummary, "public_state">;

function coordinate(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function mapLayout(entities: Positioned[], presentation?: MapPresentation) {
  const points = entities.flatMap(entity => {
    const x = coordinate(entity.public_state?.x), y = coordinate(entity.public_state?.y);
    return x === null || y === null ? [] : [{ x, y }];
  });
  if (presentation && points.every(point => point.x >= presentation.min_x && point.x <= presentation.max_x && point.y >= presentation.min_y && point.y <= presentation.max_y)) {
    return { bounds: presentation as GridBounds, imagePath: presentation.image_path, autoScaled: false };
  }
  const bounds: GridBounds = points.length ? {
    min_x: Math.min(...points.map(point => point.x)) - 1, max_x: Math.max(...points.map(point => point.x)) + 1,
    min_y: Math.min(...points.map(point => point.y)) - 1, max_y: Math.max(...points.map(point => point.y)) + 1,
  } : { min_x: -4, max_x: 4, min_y: -4, max_y: 4 };
  return { bounds, imagePath: null, autoScaled: true };
}

export function entityMapPosition(entity: Positioned, bounds: GridBounds): CSSProperties | null {
  const x = coordinate(entity.public_state?.x), y = coordinate(entity.public_state?.y);
  if (x === null || y === null || x < bounds.min_x || x > bounds.max_x || y < bounds.min_y || y > bounds.max_y) return null;
  return {
    left: `${(x - bounds.min_x + 0.5) / (bounds.max_x - bounds.min_x + 1) * 100}%`,
    top: `${(y - bounds.min_y + 0.5) / (bounds.max_y - bounds.min_y + 1) * 100}%`,
  };
}
