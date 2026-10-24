/** The recorded inspection of Emerson's example cabinet (sample 01) in photo pixels: drawing layout, anchors and the
 *  four FAILs. The hero viewport, the exploded story and the X-ray lens all draw from this one real run. */
import data from "../data/showcase.json";
import type { Pt } from "./types";

export const SHOW = data as unknown as {
  photo_size: [number, number];
  backplate: Pt[];
  layout: { tag: string; kind: string; quad: Pt[] }[];
  anchors: { tag: string; inlier: boolean; p: Pt }[];
  issues: { id: string; marker: number; result: string; found: string; expected: string; check: string; quad: Pt[] }[];
  counts: Record<string, number>;
};

export const [SW, SH] = SHOW.photo_size;
export const pts = (q: Pt[]) => q.map((p) => p.join(",")).join(" ");
export const bb = (q: Pt[]) => {
  const xs = q.map((p) => p[0]);
  const ys = q.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
};

/** Drawing items the inspection found wrong (their tag is the subject of a FAIL). */
const FAILED = new Set(["PS12", "CB43", "CB44", "1CBP03", "X3:3"]);
export const isFailedTag = (tag: string) => FAILED.has(tag);

/** Short proof label per FAIL, as the console words it. */
export const ISSUE_TEXT: Record<string, string> = {
  "GA-PS12": "PS12 missing",
  "ORD-RAIL-1": "CB43 ↔ CB44 swapped",
  "LBL-1CBP03": "1CBP03 no label",
  "FER-X3:3": "X3:3 no ferrule",
};

/** What the lens reads on a failed drawing item. */
export const TAG_FAULT: Record<string, string> = {
  PS12: "missing",
  CB43: "swapped with CB44",
  CB44: "swapped with CB43",
  "1CBP03": "no label",
  "X3:3": "no ferrule",
};

/** Nearest drawing item to a point (photo px), for the X-ray lens readout. */
export function nearestItem(x: number, y: number) {
  let best: { tag: string; d: number; c: Pt; fail: boolean } | null = null;
  for (const l of SHOW.layout) {
    const b = bb(l.quad);
    const c: Pt = [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
    const d = Math.hypot(c[0] - x, c[1] - y);
    if (!best || d < best.d) best = { tag: l.tag, d, c, fail: FAILED.has(l.tag) };
  }
  return best;
}
