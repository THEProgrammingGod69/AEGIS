export interface PolygonBounds { x0: number; y0: number; x1: number; y1: number }

/** An unlocated finding has no polygon. It must never move the image viewport to NaN. */
export function polygonBounds(points: unknown): PolygonBounds | null {
  if (!Array.isArray(points) || points.length < 3 || points.some((p) => !Array.isArray(p) || p.length < 2 || !Number.isFinite(p[0]) || !Number.isFinite(p[1]))) return null;
  const xs = points.map((p) => p[0] as number);
  const ys = points.map((p) => p[1] as number);
  const b = { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  return b.x1 > b.x0 && b.y1 > b.y0 ? b : null;
}

export type Mat3 = number[][];

/** Point through a 3x3 projective matrix (row-major). */
export function applyH(m: Mat3, p: [number, number]): [number, number] {
  const w = m[2][0] * p[0] + m[2][1] * p[1] + m[2][2];
  return [(m[0][0] * p[0] + m[0][1] * p[1] + m[0][2]) / w, (m[1][0] * p[0] + m[1][1] * p[1] + m[1][2]) / w];
}

export function inv3(m: Mat3): Mat3 | null {
  const [[a, b, c], [d, e, f], [g, h, i]] = m;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-18) return null;
  return [
    [A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
    [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
    [C / det, -(a * h - b * g) / det, (a * e - b * d) / det],
  ];
}

/** Photo px -> px of the straightened photo of a real-cabinet run: through the fitted perspective onto the drawing
 *  (pt), then the straightened image's scale k and origin. Null when the matrix cannot be inverted. */
export function straightener(r: { H: Mat3; k: number; origin: [number, number] }): ((p: [number, number]) => [number, number]) | null {
  const Hi = inv3(r.H);
  if (!Hi) return null;
  return (p) => {
    const d = applyH(Hi, p);
    return [(d[0] - r.origin[0]) * r.k, (d[1] - r.origin[1]) * r.k];
  };
}
