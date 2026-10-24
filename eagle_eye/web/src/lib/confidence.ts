/** Calibrated confidence (eagle_eye/calibration.py, fitted on Fault Forge runs), per item and per photo. Runs saved
 *  since calibration carry it; older and recorded runs are calibrated here from their raw item score with the same
 *  bundled map, so every run shows the same kind of number. */
import CAL from "../data/calibration.json";
import type { CalBin, Calibration, Item, PhotoConfidence, RunPayload } from "./types";

export const CALIBRATION = CAL as unknown as Calibration;
export type Engine = "demo" | "real";

export const engineOf = (p: RunPayload): Engine => ((p.engine_kind ?? p.meta.engine_kind) === "real" ? "real" : "demo");

function lookup(bins: CalBin[] | undefined, raw: number): number | null {
  if (!bins?.length) return null;
  const x = Math.min(1, Math.max(0, raw || 0));
  const hit = bins.find((b) => (b.lo <= x && x < b.hi) || (x >= 1 && b.hi >= 1));
  if (hit) return hit.p;
  const gap = (b: CalBin) => Math.min(Math.abs(x - b.lo), Math.abs(x - b.hi));
  return bins.reduce((best, b) => (gap(b) < gap(best) ? b : best)).p;
}

/** What an item's raw score measures: a colour measurement is calibrated apart from text reads (calibration.MEASURE). */
const measureOf = (it: Item) => ((it.check ?? (it.id.split("-")[0] === "COL" ? "COLOUR" : "")) === "COLOUR" ? "colour" : "text");

/** PASS/FAIL: probability that the verdict is right. REVIEW: probability that the item is faulty. Else null. */
export function itemConfidence(it: Item, eng: Engine): number | null {
  if (it.result !== "PASS" && it.result !== "FAIL" && it.result !== "REVIEW") return null;
  if (typeof it.confidence === "number") return it.confidence;
  const cal = CALIBRATION.engines[eng];
  if (cal?.measures && !cal.measures.includes(measureOf(it))) return null;
  return lookup(cal?.maps[it.result], it.conf);
}

export function photoConfidence(p: RunPayload): PhotoConfidence | null {
  if (p.meta.confidence) return p.meta.confidence;
  const eng = engineOf(p);
  const dec: { r: Item; c: number }[] = [];
  for (const r of p.results) {
    if (r.result !== "PASS" && r.result !== "FAIL") continue;
    const c = itemConfidence(r, eng);
    if (c != null) dec.push({ r, c });
  }
  if (!dec.length) return null;
  const low = [...dec].sort((a, b) => a.c - b.c).slice(0, 3);
  return {
    score: dec.reduce((a, x) => a + x.c, 0) / dec.length,
    decided: dec.length,
    expected_errors: dec.reduce((a, x) => a + 1 - x.c, 0),
    review: p.results.filter((r) => r.result === "REVIEW").length,
    lowest: low.map((x) => ({ id: x.r.id, result: x.r.result, confidence: x.c })),
  };
}

export const pct = (c: number) => (c >= 0.995 ? ">99%" : c <= 0.005 ? "<1%" : `${Math.round(c * 100)}%`);

/** What the number means for this verdict, in words. */
export function confidenceMeaning(result: string) {
  return result === "PASS" ? "chance this PASS is right" : result === "FAIL" ? "chance this is a real fault" : "chance this item is faulty (fault likelihood)";
}

/** Colour of a confidence level: firm, worth a look, weak. REVIEW is a referral, so it keeps the review colour. */
export function confidenceColor(c: number, result: string) {
  if (result === "REVIEW") return "var(--review)";
  return c >= 0.9 ? "var(--pass)" : c >= 0.7 ? "var(--review)" : "var(--fail)";
}
