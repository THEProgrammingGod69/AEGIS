/** Human-in-the-loop helpers: the inspector's name, and an item's final status once a person has decided. */
import type { Item, Result, RunMeta } from "./types";

const KEY = "ee_inspector";

export function inspectorName(): string {
  try {
    return localStorage.getItem(KEY) || "Inspector";
  } catch {
    return "Inspector";
  }
}

export function setInspectorName(v: string) {
  try {
    localStorage.setItem(KEY, v.trim().slice(0, 80) || "Inspector");
  } catch {
    /* private window */
  }
}

/** Engine result, unless an inspector has confirmed or overridden it. */
export function finalResult(it: Pick<Item, "id" | "result">, meta: Pick<RunMeta, "reviews">): Result {
  return meta.reviews?.[it.id]?.decision ?? it.result;
}

export interface ReviewSummary {
  decided: number;
  confirmed: number;
  overridden: number;
  pending: number;
  fails: number;
}

/** Counts after review: open REVIEW items still pending, FAILs the inspector kept or overturned. */
export function reviewSummary(meta: RunMeta, items: { id: string; result: Result }[] = meta.issues): ReviewSummary {
  const r = meta.reviews ?? {};
  let confirmed = 0, overridden = 0, pending = 0, fails = 0;
  for (const it of items) {
    const d = r[it.id];
    if (d) (d.decision === it.result ? confirmed++ : overridden++);
    else if (it.result === "REVIEW") pending++;
    if ((d?.decision ?? it.result) === "FAIL") fails++;
  }
  return { decided: Object.keys(r).length, confirmed, overridden, pending, fails };
}

/** Verdict once every REVIEW item has a human decision. */
export function finalVerdict(meta: RunMeta): "PASS" | "HOLD" | "REVIEW" {
  if (meta.verdict.label === "REVIEW" && meta.warnings?.some((w) => w.code === "weak_registration")) return "REVIEW";
  const s = reviewSummary(meta);
  if (s.fails) return "HOLD";
  if (s.pending) return "REVIEW";
  return "PASS";
}
