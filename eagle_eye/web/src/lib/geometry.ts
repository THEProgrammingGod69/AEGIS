export interface PolygonBounds { x0: number; y0: number; x1: number; y1: number }

/** An unlocated finding has no polygon. It must never move the image viewport to NaN. */
export function polygonBounds(points: unknown): PolygonBounds | null {
  if (!Array.isArray(points) || points.length < 3 || points.some((p) => !Array.isArray(p) || p.length < 2 || !Number.isFinite(p[0]) || !Number.isFinite(p[1]))) return null;
  const xs = points.map((p) => p[0] as number);
  const ys = points.map((p) => p[1] as number);
  const b = { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  return b.x1 > b.x0 && b.y1 > b.y0 ? b : null;
}
