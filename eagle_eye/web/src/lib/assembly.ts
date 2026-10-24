/** Where a finding belongs on the assembly line: device family, cabinet area and the line station that fixes it.
 *  Runs saved since the fault Pareto carry these (eagle_eye/assembly.py); older runs are placed here with the same
 *  rules, using the demo drawing's rails and device kinds from the heatmap's base run. */
import type { RunMeta, RunPayload } from "./types";

type Issue = RunMeta["issues"][number];
export interface Dims { check: string; target: string; family: string; area: string; station: string }

export const STATION: Record<string, string> = {
  GA: "Kitting and mounting", MISSING: "Kitting and mounting", ORDER: "Mounting (rail layout)", LABEL: "Labelling",
  UNKNOWN_LABEL: "Labelling", FERRULE: "Wiring (ferrules)", COLOUR: "Wiring (wire colours)",
};
const FAMILY_NAME: Record<string, string> = {
  CSLS: "CHARM carrier", CBP: "CHARM baseplate", RDEW: "Cabinet nameplate", TERM: "CHARM terminator", RCCB: "Residual-current breaker",
  SPD: "Surge protector", REC: "Socket outlet", FILTER: "Filter", XALM: "Alarm terminal", FSW: "Fan switch", CB: "Circuit breaker",
  PS: "Power supply", DS: "Disconnect switch", D: "Redundancy module", SB: "Shield bar", TS: "Thermostat", CF: "Cabinet fan",
  CL: "Cabinet light", X: "Terminal block", EARTH: "Earth bar",
};
const FAMILIES: [string, RegExp][] = [
  ["CSLS", /^\d{2}CSLS\d{5}$/], ["CBP", /^\d{3}CBP\d{2}$/], ["RDEW", /^\d{2}RDEW-\d{2}[A-Z]\d{3}[A-Z]{1,2}$/], ["TERM", /^TERM\d[FR]$/],
  ["RCCB", /^RCCB\d{1,2}$/], ["SPD", /^SPD\d{1,2}$/], ["REC", /^REC\d{1,2}$/], ["FILTER", /^FILTER\d{1,2}$/],
  ["XALM", /^(?:X|ALM)-[A-Z]+\d{0,2}$/], ["FSW", /^FSW\d{1,2}$/], ["CB", /^CB\d{1,3}$/], ["PS", /^PS\d{1,3}$/], ["DS", /^DS\d{1,3}$/],
  ["D", /^D\d{2}$/], ["SB", /^SB\d{2}$/], ["TS", /^TS\d{1,2}$/], ["CF", /^CF\d{1,2}$/], ["CL", /^CL\d{1,2}$/], ["X", /^X[A-Z]?\d{1,3}$/],
  ["EARTH", /^(?:IPE|IE|ISE|ISG|DCG)$/],
];
/** demo drawing (EE-DEMO-01): device kind -> family and backplate zone */
const DEMO_KIND: Record<string, [string, string]> = {
  psu: ["Power supply", "Power supply row"], controller: ["Controller", "Power supply row"], breaker: ["Circuit breaker", "Breaker rail"],
  baseplate: ["I/O baseplate", "I/O baseplates"], earth: ["Earth bar", "Earth bar"],
};
const PREFIX: Record<string, string> = { GA: "GA", ORD: "ORDER", LBL: "LABEL", FER: "FERRULE", COL: "COLOUR", MISS: "MISSING", UNK: "UNKNOWN_LABEL" };

export const checkOfId = (id: string) => PREFIX[id.split("-")[0]] ?? id.split("-")[0];

export function familyName(tag: string) {
  const t = tag.toUpperCase().replace(/[^A-Z0-9\-/]/g, "");
  for (const [f, rx] of FAMILIES) if (rx.test(t)) return FAMILY_NAME[f] ?? f;
  const letters = t.replace(/[^A-Z]/g, "");
  return FAMILY_NAME[letters] ?? (letters || "Other");
}

export function issueDims(i: Issue, base: RunPayload | null): Dims {
  const check = i.check ?? checkOfId(i.id);
  const target = i.target ?? i.id.slice(i.id.indexOf("-") + 1);
  const station = i.station ?? STATION[check] ?? "Final inspection";
  if (i.family && i.area) return { check, target, family: i.family, area: i.area, station };
  if (check === "FERRULE" || check === "COLOUR" || target.includes(":"))
    return { check, target, family: check === "COLOUR" ? "Wire" : check === "FERRULE" ? "Wire ferrule" : "Terminal block", area: `Terminal strip ${target.split(":")[0]}`, station };
  let family = familyName(target);
  let area = "Area not recorded";
  if (base && (base.engine_kind ?? base.meta.engine_kind) !== "real") {
    const rail = base.rails?.find((r) => r.name === target || r.tags.includes(target));
    const kindOf = (t: string) => base.layout.find((l) => l.tag === t)?.kind;
    const kind = rail && rail.name === target ? rail.tags.map(kindOf).find(Boolean) : kindOf(target);
    const k = kind ? DEMO_KIND[kind] : undefined;
    if (k) family = k[0];
    area = rail ? (family === "Circuit breaker" ? `Breaker rail (${rail.name})` : `Rail ${rail.name}`) : k ? k[1] : "Backplate";
  }
  return { check, target, family, area, station };
}

export type ParetoBy = "fault" | "family" | "area" | "station";

export interface ParetoRow {
  key: string;
  label: string;
  n: number;
  share: number;
  cum: number;
  ids: Set<string>;
  /** fault mode: where it belongs; other modes: the items that make it up */
  family?: string;
  area?: string;
  station?: string;
  top?: string[];
}

/** Recurring FAILs across runs, ranked: the top ``limit`` groups plus one "Other" row, with share and cumulative share. */
export function pareto(metas: RunMeta[], by: ParetoBy, base: RunPayload | null, limit = 5): { rows: ParetoRow[]; total: number } {
  const groups = new Map<string, ParetoRow & { items: Map<string, number> }>();
  let total = 0;
  for (const m of metas)
    for (const i of m.issues) {
      if (i.result !== "FAIL") continue;
      total++;
      const d = issueDims(i, base);
      const key = by === "fault" ? i.id : by === "family" ? d.family : by === "area" ? d.area : d.station;
      const g = groups.get(key) ?? { key, label: key, n: 0, share: 0, cum: 0, ids: new Set<string>(), items: new Map<string, number>(),
        ...(by === "fault" ? { family: d.family, area: d.area, station: d.station } : {}) };
      g.n++;
      g.ids.add(i.id);
      g.items.set(i.id, (g.items.get(i.id) ?? 0) + 1);
      groups.set(key, g);
    }
  const sorted = [...groups.values()].sort((a, b) => b.n - a.n || a.key.localeCompare(b.key));
  const head = sorted.slice(0, limit);
  const rest = sorted.slice(limit);
  const rows: ParetoRow[] = head.map(({ items, ...g }) => ({ ...g, top: [...items.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([id]) => id) }));
  if (rest.length)
    rows.push({ key: "__other", label: `Other (${rest.length})`, n: rest.reduce((a, g) => a + g.n, 0), share: 0, cum: 0,
      ids: new Set(rest.flatMap((g) => [...g.ids])) });
  let cum = 0;
  for (const r of rows) {
    r.share = total ? r.n / total : 0;
    cum += r.n;
    r.cum = total ? cum / total : 0;
  }
  return { rows, total };
}
