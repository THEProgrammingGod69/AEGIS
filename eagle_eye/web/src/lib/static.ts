/**
 * Hosted console (`npm run build:static`, eagle-eye-enigma.vercel.app).
 *
 * Two sources behind one API (mirrors api.ts):
 *  - the cloud engine (cloud.ts): the real Python engine in a container. Uploads, custom drawing sets, re-checks,
 *    toggled checks and Fault Forge with any seed run live; the browser keeps the results (store.ts).
 *  - recorded runs (export_static.py): genuine engine runs replayed with their stage timings. Used when the
 *    viewer picks "recorded", or automatically when the engine cannot be reached, so the demo never breaks.
 */
import { ENGINE_URL, EngineUnreachable, NeedFiles, b64Blob, compactPdf, postInput, engine, ensureEngine, liveReady, makePreview, preparePhoto, renderMarked, sha256, stream, type StreamResult } from "./cloud";
import * as store from "./store";
import type { InputKey, LiveRun } from "./store";
import type { CheckInfo, ForgeLive, Health, JobEvent, JobView, Preset, Review, RunMeta, RunPayload, Sample, SelfTest } from "./types";
import type { InspectInput } from "./api";

const BASE = "demo/";
export const REPO_URL = "https://github.com/THEProgrammingGod69/AEGIS";
export const LIVE_ONLY =
  "The cloud engine is not reachable right now, so only the recorded runs can be replayed. Retry from the engine status at the top right, or run the engine locally (eagle_eye/run.bat or ./run.sh).";

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
const live = new Map<string, LiveRun>();
const blobUrls = new Map<string, Record<string, string>>();
const MAX_LIVE = 40;

const MIME: Record<string, string> = {
  photo: "image/jpeg", preview: "image/jpeg", rectified: "image/jpeg", marked: "image/jpeg", ga: "image/jpeg", overlay: "image/png",
  pdf: "application/pdf", checklist: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", json: "application/json",
};

function mount(run: LiveRun) {
  live.set(run.id, run);
  const u: Record<string, string> = {};
  for (const [k, b] of Object.entries(run.files)) u[k] = URL.createObjectURL(b);
  blobUrls.set(run.id, u);
}

function unmount(id: string) {
  Object.values(blobUrls.get(id) ?? {}).forEach((u) => URL.revokeObjectURL(u));
  blobUrls.delete(id);
  live.delete(id);
}

export async function loadStatic() {
  const [ix, saved] = await Promise.all([fetch(BASE + "index.json").then((r) => r.json()), store.loadAll().catch(() => [])]);
  IX = ix;
  saved.forEach(mount);
}

const known = (id: string) => !!IX.runs[id] || live.has(id);
export const isLiveRun = (id: string) => live.has(id);

/** GA raster for proof crops: the run's own drawing (custom GA on the cloud engine) or the demo drawing. */
export function gaFor(run?: string) {
  const l = run ? live.get(run) : undefined;
  if (l?.payload.ga_raster && blobUrls.get(run!)?.ga) return { ...l.payload.ga_raster, src: blobUrls.get(run!)!.ga };
  return { ...IX.ga, src: BASE + IX.ga.src };
}
export const gaRaster = () => gaFor();

/* ---------------- per-browser state: history, Fault Forge tally, inspector reviews ---------------- */
function load(key: string, fallback: string[], legacy?: string): string[] {
  try {
    const v = localStorage.getItem(key) ?? (legacy ? localStorage.getItem(legacy) : null);
    return v ? (JSON.parse(v) as string[]).filter(known) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* private window: keep in memory only */
  }
}
let history: string[] | null = null;
let forged: string[] | null = null;
const hist = () => (history ??= load("ee_history_v2", IX.history, "ee_history_v1"));
const forgeDone = () => (forged ??= load("ee_forge_v2", [], "ee_forge_v1"));
function remember(ids: string[], isForge: boolean) {
  history = [...hist().filter((x) => !ids.includes(x)), ...ids];
  save("ee_history_v2", history);
  if (isForge) {
    forged = [...forgeDone().filter((x) => !ids.includes(x)), ...ids];
    save("ee_forge_v2", forged);
  }
}

let reviews: Record<string, Record<string, Review>> | null = null;
const allReviews = () => {
  if (reviews) return reviews;
  try {
    reviews = JSON.parse(localStorage.getItem("ee_reviews_v1") ?? "{}");
  } catch {
    reviews = {};
  }
  return reviews!;
};

function metaOf(id: string): RunMeta | null {
  const m = IX.runs[id]?.meta ?? live.get(id)?.meta;
  if (!m) return null;
  return { ...m, reviews: allReviews()[id] ?? {}, origin: live.has(id) ? "cloud" : "recorded" };
}

/** Keep the newest MAX_LIVE cloud runs on this device. */
async function evict() {
  const ids = [...live.values()].sort((a, b) => a.saved - b.saved).map((r) => r.id);
  const drop = ids.slice(0, Math.max(0, ids.length - MAX_LIVE));
  if (!drop.length) return;
  drop.forEach(unmount);
  history = hist().filter((x) => !drop.includes(x));
  forged = forgeDone().filter((x) => !drop.includes(x));
  save("ee_history_v2", history);
  save("ee_forge_v2", forged);
  await store.remove(drop);
}

/**
 * Keep a cloud run on this device as metadata: payload, report, PDF, checklist, drawing crops, plus a small preview
 * of the photo (made here from the photo the browser already has, or sent by the engine for photos it generated)
 * and the marked-up preview drawn from the boxes. The full photo is never stored.
 */
async function keep(r: StreamResult, events: JobEvent[], inputs?: LiveRun["inputs"], photo?: Blob | null): Promise<string> {
  const files: Record<string, Blob> = {};
  for (const [k, v] of Object.entries(r.files)) {
    if (k === "preview") continue;
    files[k] = b64Blob(v, MIME[k] ?? (k.startsWith("exp:") ? "image/jpeg" : "application/octet-stream"));
  }
  if (r.files.preview) files.photo = b64Blob(r.files.preview, "image/jpeg");
  else if (r.files.photo) files.photo = b64Blob(r.files.photo, "image/jpeg");      // engines older than metadata-first
  else if (photo) files.photo = await makePreview(photo).catch(() => photo);
  if (files.photo && !files.marked) files.marked = await renderMarked(files.photo, r.payload).catch(() => files.photo);
  files.json = new Blob([JSON.stringify(r.report, null, 1)], { type: MIME.json });
  const run: LiveRun = { id: r.payload.meta.id, meta: { ...r.payload.meta, origin: "cloud" }, payload: r.payload, report: r.report, events, files, inputs, saved: Date.now() };
  mount(run);
  await store.put(run);
  return run.id;
}

/* ---------------- jobs: replays of recorded runs, or live cloud runs ---------------- */
interface Job {
  id: string;
  kind: JobView["kind"];
  mode: "recorded" | "cloud";
  label: string;
  parent: string | null;
  count: number;
  start: number;
  // replay
  timeline: { at: number; ev: JobEvent }[];
  doneAt: number[];
  total: number;
  // live
  status: JobView["status"];
  events: JobEvent[];
  runs: string[];
  error: string | null;
  finished: number | null;
  queue: number;
  note?: string;
  done: boolean;
}
const jobs = new Map<string, Job>();
const newId = () => Math.random().toString(36).slice(2, 14);

function replay(j: Job, runIds: string[]) {
  const timeline: Job["timeline"] = [];
  const doneAt: number[] = [];
  let offset = 0;
  runIds.forEach((rid, i) => {
    if (j.kind === "forge") timeline.push({ at: offset, ev: { stage: "cabinet", status: "start", t: 0, index: i + 1, count: runIds.length } });
    const evs = IX.runs[rid].events;
    evs.forEach((ev) => timeline.push({ at: offset + ev.t, ev }));
    offset += (evs.length ? evs[evs.length - 1].t : 1) + 0.35;
    doneAt.push(offset);
  });
  Object.assign(j, { mode: "recorded", runs: runIds, timeline, doneAt, total: offset, start: performance.now(), count: runIds.length, status: "running" });
}

function startReplay(kind: Job["kind"], runIds: string[], label: string, parent: string | null, note?: string): JobView {
  const j = blank(kind, label, parent);
  j.note = note;
  replay(j, runIds);
  jobs.set(j.id, j);
  return view(j, 0);
}

function blank(kind: Job["kind"], label: string, parent: string | null): Job {
  return {
    id: newId(), kind, mode: "cloud", label, parent, count: 1, start: performance.now(), timeline: [], doneAt: [], total: 0,
    status: "running", events: [], runs: [], error: null, finished: null, queue: 0, done: false,
  };
}

/** Run `work` against the cloud engine; if the engine cannot be reached and a recorded run exists, replay it. */
function startLive(kind: Job["kind"], label: string, parent: string | null, work: (j: Job) => Promise<void>, fallback?: () => string[] | null): JobView {
  const j = blank(kind, label, parent);
  jobs.set(j.id, j);
  work(j)
    .then(() => {
      j.status = "done";
      j.finished = performance.now();
      j.done = true;
      remember(j.runs, kind === "forge");
      void evict();
    })
    .catch((e: Error) => {
      const alt = e instanceof EngineUnreachable && fallback ? fallback() : null;
      if (alt && alt.length && !j.runs.length) {
        j.events = [];
        j.note = "The cloud engine did not answer, so the recorded run of the same inspection is shown.";
        replay(j, alt);
      } else {
        j.status = "error";
        j.error = e.message;
        j.finished = performance.now();
        if (j.runs.length) remember(j.runs, kind === "forge");
      }
    });
  return view(j, 0);
}

function view(j: Job, since: number): JobView {
  const base = { id: j.id, kind: j.kind, label: j.label, parent: j.parent, count: j.count, mode: j.mode, note: j.note };
  if (j.mode === "recorded") {
    const elapsed = (performance.now() - j.start) / 1000;
    const done = elapsed >= j.total;
    if (done && !j.done) {
      j.done = true;
      remember(j.runs, j.kind === "forge");
    }
    const evs = j.timeline.filter((x) => x.at <= elapsed).map((x) => x.ev);
    const finishedRuns = j.runs.filter((_, i) => j.doneAt[i] <= elapsed);
    return {
      ...base, status: done ? "done" : "running", events: evs.slice(since), n_events: evs.length,
      runs: done ? j.runs : finishedRuns, run_id: done ? j.runs[j.runs.length - 1] : null, error: null,
      queue_position: 0, elapsed: Math.min(elapsed, j.total),
    };
  }
  return {
    ...base, status: j.status === "running" && j.queue ? "queued" : j.status, events: j.events.slice(since), n_events: j.events.length,
    runs: [...j.runs], run_id: j.status === "done" ? j.runs[j.runs.length - 1] ?? null : null, error: j.error,
    queue_position: j.queue, elapsed: ((j.finished ?? performance.now()) - j.start) / 1000,
  };
}

const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];

export function recheckOptions(parent: string): string[] {
  return Object.keys(IX.recheck[parent] ?? {});
}

async function parentData(parent: string) {
  const meta = metaOf(parent);
  if (!meta) throw new Error(`Run ${parent} is not on this device any more`);
  const report = live.get(parent)?.report ?? (await (await fetch(BASE + IX.runs[parent].files.json)).json());
  return new Blob([JSON.stringify({ meta, report })], { type: "application/json" });
}

function recordedFor(i: InspectInput): string[] | null {
  if (i.photo || i.ga || i.wires || i.checklist || i.preset) return null;
  if (i.checks && IX.enabled.some((c) => !i.checks!.includes(c))) return null;
  const sample = i.sample ?? "01";
  if (i.parent) {
    const rid = IX.recheck[i.parent]?.[sample];
    return rid ? [rid] : null;
  }
  return IX.base[sample] ? [IX.base[sample]] : null;
}

function sampleLabel(sample: string) {
  const s = IX.samples.find((x) => x.id === sample);
  return `Sample ${sample} · ${s?.title ?? ""}`;
}

/* ---------------- API surface (mirrors api.ts) ---------------- */
export const staticApi = {
  health: async (): Promise<Health> => {
    const e = engine();
    if (e.state === "ready" && e.health && e.preferLive) return { ...e.health, runs: hist().length, mode: "cloud" };
    return { ...IX.health, runs: hist().length, mode: "recorded" };
  },
  checks: async () => IX.checks,
  samples: async (): Promise<Sample[]> => IX.samples,
  inputs: async () => IX.inputs,
  /** Real drawing sets the cloud engine holds (mounted EAGLE_EYE_REAL_DATA); none in replay mode. */
  presets: async (): Promise<Preset[]> => {
    if (!(await ensureEngine())) return [];
    try {
      const r = await fetch(`${ENGINE_URL}/api/v2/presets`, { cache: "no-store" });
      return r.ok ? ((await r.json()) as Preset[]) : [];
    } catch {
      return [];
    }
  },
  runs: async (): Promise<RunMeta[]> => [...hist()].reverse().map(metaOf).filter((m): m is RunMeta => !!m),
  run: async (id: string): Promise<RunPayload> => {
    const l = live.get(id);
    if (l) return { ...l.payload, meta: metaOf(id)! };
    if (!IX.runs[id]) throw new Error(`Run ${id} is not on this device (cloud runs are kept in the browser that ran them).`);
    const p: RunPayload = await (await fetch(`${BASE}runs/${id}/payload.json`)).json();
    return { ...p, meta: metaOf(id)! };
  },
  chain: async (id: string): Promise<RunMeta[]> => {
    const root = metaOf(id)?.root ?? id;
    const ids = new Set([...hist(), id]);
    return [...ids].map(metaOf).filter((m): m is RunMeta => !!m && (m.root || m.id) === root)
      .sort((a, b) => a.version - b.version || a.id.localeCompare(b.id));
  },
  clearRuns: async () => {
    const n = hist().length;
    [...live.keys()].forEach(unmount);
    await store.clearAll();
    history = [];
    forged = [];
    reviews = {};
    save("ee_history_v2", []);
    save("ee_forge_v2", []);
    save("ee_reviews_v1", {});
    return { deleted: n };
  },
  job: async (id: string, since = 0): Promise<JobView> => {
    const j = jobs.get(id);
    if (!j) throw new Error("unknown job");
    return view(j, since);
  },
  forgeLive: async (): Promise<ForgeLive> => {
    const metas = forgeDone().map(metaOf).filter((m): m is RunMeta => !!m?.forge);
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
    const recorded = () => {
      let pool = IX.forge.filter((id) => body.faults == null || IX.runs[id].meta.forge!.score.n_planted === body.faults);
      if (!pool.length) pool = IX.forge;
      const left = [...pool].sort(() => Math.random() - 0.5);
      return Array.from({ length: body.count }, () => (left.length ? left.shift()! : pick(pool)));
    };
    const label = `Fault Forge × ${body.count}`;
    if (!(await ensureEngine())) return startReplay("forge", recorded(), label, null);
    return startLive("forge", label, null, async (j) => {
      j.count = body.count;
      for (let i = 0; i < body.count; i++) {
        j.events.push({ stage: "cabinet", status: "start", t: 0, index: i + 1, count: body.count });
        const seed = body.seed == null ? null : body.seed + i;
        await stream("/api/v2/forge", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ faults: body.faults, strength: body.strength, seed }),
        }, {
          onEvent: (ev) => { j.queue = 0; j.events.push(ev); },
          onQueued: (n) => { j.queue = n; },
          onResult: async (r) => { j.runs.push(await keep(r, j.events.slice())); },
        });
      }
    }, recorded);
  },
  inspect: async (i: InspectInput): Promise<JobView> => {
    const sample = i.sample ?? "01";
    const rec = recordedFor(i);
    const label = i.photo ? `Upload · ${i.photo.name}` : i.preset ? `Real cabinet · ${i.presetPhoto ?? ""}` : sampleLabel(sample);
    const kind = i.parent ? "recheck" : "inspect";
    if (!(await ensureEngine())) {
      if (!rec) {
        if (i.parent && !i.photo && !i.ga && !i.wires && !i.checklist)
          throw new Error(`The cloud engine is offline and this re-check (sample ${sample}) was not recorded. Try ${recheckOptions(i.parent).join(", ") || "Sample 01"}, or retry the engine.`);
        if (i.checks && !i.photo) throw new Error("Switching plug-in checks off needs the cloud engine, which is offline right now. The recorded runs use all five checks.");
        throw new Error(LIVE_ONLY);
      }
      return startReplay(kind, rec, (i.parent ? "Re-check · " : "") + label, i.parent ?? null);
    }
    return startLive(kind, (i.parent ? "Re-check · " : "") + label, i.parent ?? null, async (j) => {
      // Metadata first: fingerprints go before files. The engine answers from what it already holds (stored
      // results, drawing sets) and asks (409) only for the files it does not have.
      const photo = i.photo ? await preparePhoto(i.photo) : null;
      const photoSha = photo ? await sha256(photo) : null;
      // a re-check reuses the drawing set of the run it re-checks, unless a new one is given
      const parentInputs = i.parent ? live.get(i.parent)?.inputs : undefined;
      const inputs: LiveRun["inputs"] = {};
      const shas: Partial<Record<InputKey, string>> = {};
      for (const k of ["ga", "wires", "checklist"] as InputKey[]) {
        const f = i[k];
        const given = f ? { name: f.name, blob: await compactPdf(f as Blob, f.name) } : parentInputs?.[k];
        if (given) {
          inputs[k] = given;
          shas[k] = await sha256(given.blob);
        }
      }
      const parentBlob = i.parent ? await parentData(i.parent) : null;
      const send = async (need: Set<string>) => {
        const fd = new FormData();
        if (photo) {
          fd.append("photo_sha", photoSha!);
          fd.append("photo_name", i.photo!.name);
          if (need.has("photo")) fd.append("photo", photo, photo.name);
        } else if (i.preset) {
          fd.append("preset", i.preset);
          if (i.presetPhoto) fd.append("preset_photo", i.presetPhoto);
        } else fd.append("sample", sample);
        for (const k of Object.keys(inputs) as InputKey[]) {
          fd.append(`${k}_sha`, shas[k]!);
          fd.append(`${k}_name`, inputs[k]!.name);
          if (need.has(k)) fd.append(k, inputs[k]!.blob, inputs[k]!.name);
        }
        if (i.checks) fd.append("checks", i.checks.join(","));
        if (parentBlob) fd.append("parent", parentBlob, "parent.json");
        await stream("/api/v2/inspect", { method: "POST", body: fd }, {
          onEvent: (ev) => { j.queue = 0; j.events.push(ev); },
          onQueued: (n) => { j.queue = n; },
          onResult: async (r) => { j.runs.push(await keep(r, j.events.slice(), Object.keys(inputs).length ? inputs : undefined, photo)); },
        });
      };
      // Each request stays under the host's body cap: inputs the engine asks for travel on their own request
      // (stored by fingerprint), then the inspection carries only the photo if it is needed at all.
      let need = new Set<string>();
      for (let attempt = 0; ; attempt++) {
        for (const k of Object.keys(inputs) as InputKey[]) {
          if (need.has(k)) {
            await postInput(k, inputs[k]!.blob, inputs[k]!.name);
            need.delete(k);
          }
        }
        try {
          await send(need);
          break;
        } catch (e) {
          if (!(e instanceof NeedFiles) || attempt >= 3) throw e;
          j.events = [];
          need = new Set(e.need);
        }
      }
    }, () => rec);
  },
  review: async (rid: string, item: string, decision: Review["decision"] | "CLEAR", note = "", by = "Inspector"): Promise<RunMeta> => {
    const all = allReviews();
    const r = { ...(all[rid] ?? {}) };
    if (decision === "CLEAR") delete r[item];
    else r[item] = { decision, note: note.slice(0, 500), by: by.slice(0, 80) || "Inspector", at: new Date().toISOString().slice(0, 19) };
    all[rid] = r;
    save("ee_reviews_v1", all);
    return metaOf(rid)!;
  },
};

export const staticUrl = {
  sample: (id: string) => BASE + (IX.samples.find((s) => s.id === id)?.image ?? ""),
  /** Full-resolution sample photo (Robustness Lab perturbs the original, not the web preview). */
  sampleFull: (id: string) => BASE + "samples/" + (IX.samples.find((s) => s.id === id)?.file ?? ""),
  file: (run: string, name: string) => {
    const u = blobUrls.get(run);
    if (u) return u[name] ?? (name === "overlay" ? BASE + "img/overlay.png" : "");
    return BASE + (IX.runs[run]?.files[name] ?? "");
  },
  download: (run: string, name: string) => staticUrl.file(run, name),
  crop: () => "",
  input: (key: string) => BASE + (IX.inputs[key]?.href ?? ""),
  presetPhoto: (id: string, file: string, w = 360) => `${ENGINE_URL}/api/v2/presets/${id}/photos/${encodeURIComponent(file)}?w=${w}`,
  gaPreview: () => BASE + "img/ga_preview.png",
};

/** Is a run usable as a live re-check parent / has a recorded alternative? (UI hints) */
export const liveNow = () => liveReady();
