/**
 * Hosted showcase mode (`npm run build:static`): the same console, backed by runs recorded from the real engine
 * (export_static.py) instead of a live server. Jobs are replayed with their recorded stage timings.
 * Inspecting a new photo needs the live engine (python server.py).
 */
import type { CheckInfo, ForgeLive, Health, JobEvent, JobView, RunMeta, RunPayload, Sample, SelfTest } from "./types";
import type { InspectInput } from "./api";

const BASE = "demo/";
export const REPO_URL = "https://github.com/THEProgrammingGod69/Code-Apex-Hackathon/tree/ccr-9309237e-ylo1qd";
export const LIVE_ONLY =
  "This hosted showcase replays inspections recorded from the real engine. Inspecting your own photo or drawing set needs the live engine: run eagle_eye/run.bat (Windows) or ./run.sh, then open http://127.0.0.1:8000.";

interface RecordedRun {
  meta: RunMeta;
  files: Record<string, string>;
  events: JobEvent[];
}

interface Index {
  version: string;
  health: Health;
  checks: CheckInfo[];
  samples: (Sample & { image: string })[];
  inputs: Record<string, { name: string; size: number; href: string }>;
  selftest: SelfTest;
  ga: { src: string; w: number; h: number; ox: number; oy: number; k: number };
  runs: Record<string, RecordedRun>;
  base: Record<string, string>;
  recheck: Record<string, Record<string, string>>;
  forge: string[];
  history: string[];
  enabled: string[];
}

let IX: Index;

export async function loadStatic() {
  IX = await (await fetch(BASE + "index.json")).json();
}

export const gaRaster = () => ({ ...IX.ga, src: BASE + IX.ga.src });

/* ---------------- per-browser session state (history, live Fault Forge tally) ---------------- */
function load(key: string, fallback: string[]): string[] {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as string[]).filter((id) => IX.runs[id]) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, v: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* private window: keep in memory only */
  }
}
let history: string[] | null = null;
let forged: string[] | null = null;
const hist = () => (history ??= load("ee_history_v1", IX.history));
const forgeDone = () => (forged ??= load("ee_forge_v1", []));
function remember(ids: string[], isForge: boolean) {
  history = [...hist().filter((x) => !ids.includes(x)), ...ids];
  save("ee_history_v1", history);
  if (isForge) {
    forged = [...forgeDone(), ...ids];
    save("ee_forge_v1", forged);
  }
}

/* ---------------- replayed jobs ---------------- */
interface Job {
  id: string;
  kind: JobView["kind"];
  runs: string[];
  start: number;
  timeline: { at: number; ev: JobEvent }[];
  doneAt: number[];
  total: number;
  label: string;
  parent: string | null;
  done: boolean;
}
const jobs = new Map<string, Job>();

function startJob(kind: Job["kind"], runIds: string[], label: string, parent: string | null): JobView {
  const timeline: Job["timeline"] = [];
  const doneAt: number[] = [];
  let offset = 0;
  runIds.forEach((rid, i) => {
    if (kind === "forge") timeline.push({ at: offset, ev: { stage: "cabinet", status: "start", t: 0, index: i + 1, count: runIds.length } });
    const evs = IX.runs[rid].events;
    evs.forEach((ev) => timeline.push({ at: offset + ev.t, ev }));
    offset += (evs.length ? evs[evs.length - 1].t : 1) + 0.35;
    doneAt.push(offset);
  });
  const id = Math.random().toString(36).slice(2, 14);
  jobs.set(id, { id, kind, runs: runIds, start: performance.now(), timeline, doneAt, total: offset, label, parent, done: false });
  return view(jobs.get(id)!, 0);
}

function view(j: Job, since: number): JobView {
  const elapsed = (performance.now() - j.start) / 1000;
  const done = elapsed >= j.total;
  if (done && !j.done) {
    j.done = true;
    remember(j.runs, j.kind === "forge");
  }
  const evs = j.timeline.filter((x) => x.at <= elapsed).map((x) => x.ev);
  const finishedRuns = j.runs.filter((_, i) => j.doneAt[i] <= elapsed);
  return {
    id: j.id, kind: j.kind, status: done ? "done" : "running", events: evs.slice(since), n_events: evs.length,
    runs: done ? j.runs : finishedRuns, run_id: done ? j.runs[j.runs.length - 1] : null, error: null,
    label: j.label, parent: j.parent, count: j.runs.length, queue_position: 0, elapsed: Math.min(elapsed, j.total),
  };
}

const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];

export function recheckOptions(parent: string): string[] {
  return Object.keys(IX.recheck[parent] ?? {});
}

/* ---------------- API surface (mirrors api.ts) ---------------- */
export const staticApi = {
  health: async (): Promise<Health> => ({ ...IX.health, runs: hist().length }),
  checks: async () => IX.checks,
  samples: async (): Promise<Sample[]> => IX.samples,
  inputs: async () => IX.inputs,
  runs: async (): Promise<RunMeta[]> => [...hist()].reverse().map((id) => IX.runs[id].meta),
  run: async (id: string): Promise<RunPayload> => {
    if (!IX.runs[id]) throw new Error(`Run ${id} is not part of this showcase`);
    return (await fetch(`${BASE}runs/${id}/payload.json`)).json();
  },
  chain: async (id: string): Promise<RunMeta[]> => {
    const root = IX.runs[id]?.meta.root ?? id;
    const ids = new Set([...hist(), id]);
    return [...ids].map((x) => IX.runs[x]?.meta).filter((m): m is RunMeta => !!m && (m.root || m.id) === root)
      .sort((a, b) => a.version - b.version || a.id.localeCompare(b.id));
  },
  clearRuns: async () => {
    const n = hist().length;
    history = [];
    forged = [];
    save("ee_history_v1", []);
    save("ee_forge_v1", []);
    return { deleted: n };
  },
  job: async (id: string, since = 0): Promise<JobView> => {
    const j = jobs.get(id);
    if (!j) throw new Error("unknown job");
    return view(j, since);
  },
  forgeLive: async (): Promise<ForgeLive> => {
    const metas = forgeDone().map((id) => IX.runs[id].meta);
    const sc = metas.map((m) => m.forge!.score);
    return {
      cabinets: metas.length, planted: sc.reduce((a, s) => a + s.n_planted, 0), caught: sc.reduce((a, s) => a + s.caught, 0),
      false_alarms: sc.reduce((a, s) => a + s.false_alarms.length, 0), reviews: sc.reduce((a, s) => a + s.reviews.length, 0),
      correct_items: sc.reduce((a, s) => a + s.correct_items, 0),
      runs: [...metas].reverse().map((m) => ({ id: m.id, seed: m.forge!.seed, created: m.created, planted: m.forge!.score.n_planted,
        caught: m.forge!.score.caught, false_alarms: m.forge!.score.false_alarms.length, reviews: m.forge!.score.reviews.length })),
    };
  },
  selftest: async (): Promise<SelfTest> => IX.selftest,
  forge: async (body: { faults: number | null; strength: number; seed: number | null; count: number }): Promise<JobView> => {
    let pool = IX.forge.filter((id) => body.faults == null || IX.runs[id].meta.forge!.score.n_planted === body.faults);
    if (!pool.length) pool = IX.forge;
    const chosen: string[] = [];
    const left = [...pool].sort(() => Math.random() - 0.5);
    for (let i = 0; i < body.count; i++) chosen.push(left.length ? left.shift()! : pick(pool));
    return startJob("forge", chosen, `Fault Forge × ${body.count}`, null);
  },
  inspect: async (i: InspectInput): Promise<JobView> => {
    if (i.photo || i.ga || i.wires || i.checklist) throw new Error(LIVE_ONLY);
    if (i.checks && IX.enabled.some((c) => !i.checks!.includes(c)))
      throw new Error("Switching plug-in checks off needs the live engine; the recorded runs use all five checks.");
    const sample = i.sample ?? "01";
    const s = IX.samples.find((x) => x.id === sample);
    if (i.parent) {
      const rid = IX.recheck[i.parent]?.[sample];
      if (!rid) throw new Error(`This re-check (sample ${sample}) was not recorded for this run. Try ${recheckOptions(i.parent).join(", ") || "another run"}, or use the live engine.`);
      return startJob("recheck", [rid], `Re-check · Sample ${sample}`, i.parent);
    }
    return startJob("inspect", [IX.base[sample]], `Sample ${sample} · ${s?.title ?? ""}`, null);
  },
};

export const staticUrl = {
  sample: (id: string) => BASE + (IX.samples.find((s) => s.id === id)?.image ?? ""),
  file: (run: string, name: string) => BASE + (IX.runs[run]?.files[name] ?? ""),
  download: (run: string, name: string) => BASE + (IX.runs[run]?.files[name] ?? ""),
  crop: () => "",
  input: (key: string) => BASE + (IX.inputs[key]?.href ?? ""),
  gaPreview: () => BASE + "img/ga_preview.png",
};
