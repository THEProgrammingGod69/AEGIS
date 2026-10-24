import { liveReady, useEngine } from "./cloud";
import { staticApi, staticUrl } from "./static";
import type { CheckInfo, ForgeLive, Health, JobView, Preset, Review, RunMeta, RunPayload, Sample, SelfTest } from "./types";

/** True in the hosted build (npm run build:static): cloud engine + recorded runs, history kept in the browser. */
export const STATIC = import.meta.env.VITE_STATIC === "1";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export interface InspectInput {
  photo?: File | null;
  sample?: string | null;
  ga?: File | null;
  wires?: File | null;
  checklist?: File | null;
  checks?: string[];
  parent?: string | null;
  /** real drawing set + photo found by the engine (EAGLE_EYE_REAL_DATA), e.g. the Emerson 13GE03331 preset */
  preset?: string | null;
  presetPhoto?: string | null;
}

const liveApi = {
  health: () => req<Health>("/api/health"),
  checks: () => req<CheckInfo[]>("/api/checks"),
  samples: () => req<Sample[]>("/api/samples"),
  inputs: () => req<Record<string, { name: string; size: number }>>("/api/inputs"),
  presets: () => req<Preset[]>("/api/presets"),
  runs: (limit = 200) => req<RunMeta[]>(`/api/runs?limit=${limit}`),
  run: (id: string) => req<RunPayload>(`/api/runs/${id}`),
  chain: (id: string) => req<RunMeta[]>(`/api/runs/${id}/chain`),
  clearRuns: () => req<{ deleted: number }>("/api/runs", { method: "DELETE" }),
  job: (id: string, since = 0) => req<JobView>(`/api/jobs/${id}?since=${since}`),
  forgeLive: () => req<ForgeLive>("/api/forge/live"),
  selftest: () => req<SelfTest>("/api/forge/selftest"),
  forge: (body: { faults: number | null; strength: number; seed: number | null; count: number }) =>
    req<JobView>("/api/forge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
  inspect: (i: InspectInput) => {
    const fd = new FormData();
    if (i.photo) fd.append("photo", i.photo);
    else if (i.preset) {
      fd.append("preset", i.preset);
      if (i.presetPhoto) fd.append("preset_photo", i.presetPhoto);
    } else if (i.sample) fd.append("sample", i.sample);
    if (i.ga) fd.append("ga", i.ga);
    if (i.wires) fd.append("wires", i.wires);
    if (i.checklist) fd.append("checklist", i.checklist);
    if (i.checks) fd.append("checks", i.checks.join(","));
    if (i.parent) fd.append("parent", i.parent);
    return req<JobView>("/api/inspect", { method: "POST", body: fd });
  },
  review: (rid: string, item: string, decision: Review["decision"] | "CLEAR", note = "", by = "Inspector") =>
    req<RunMeta>(`/api/runs/${rid}/review`, {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ item, decision, note, by }),
    }),
};

const liveUrl = {
  sample: (id: string, w = 0) => `/api/samples/${id}/image${w ? `?w=${w}` : ""}`,
  sampleFull: (id: string) => `/api/samples/${id}/image`,
  file: (run: string, name: string, w = 0) => `/api/runs/${run}/files/${name}${w ? `?w=${w}` : ""}`,
  download: (run: string, name: string) => `/api/runs/${run}/files/${name}?download=1`,
  crop: (run: string, item: string, kind: "expected" | "found" | "aligned") =>
    `/api/runs/${run}/items/${encodeURIComponent(item)}/${kind}`,
  input: (key: string) => `/api/inputs/${key}`,
  presetPhoto: (id: string, file: string, w = 360) => `/api/presets/${id}/photos/${encodeURIComponent(file)}?w=${w}`,
  gaPreview: () => "/api/inputs/ga/preview",
};

export const api: typeof liveApi = STATIC ? (staticApi as unknown as typeof liveApi) : liveApi;
export const url: typeof liveUrl = STATIC ? (staticUrl as unknown as typeof liveUrl) : liveUrl;

/** Can this console run a real inspection right now? Local engine: always. Hosted: when the cloud engine is up. */
export const canLive = () => !STATIC || liveReady();
export function useCanLive() {
  const e = useEngine();
  return !STATIC || (e.state === "ready" && e.preferLive);
}

const DL: Record<string, [string, string]> = {
  pdf: ["EAGLE_EYE_Report", "pdf"], checklist: ["QC_Checklist", "xlsx"], json: ["EAGLE_EYE", "json"], marked: ["Marked", "jpg"],
};
/** Props for a download link (hosted runs are blob URLs, so they need an explicit file name). */
export function dl(run: string, name: string, cabinet = "EE") {
  const href = url.download(run, name);
  if (!STATIC) return { href };
  const [stem, ext] = DL[name] ?? [name, "bin"];
  return name === "pdf" ? { href, target: "_blank", rel: "noreferrer" } : { href, download: `${stem}_${cabinet}_${run}.${ext}` };
}

/** Poll a job until it finishes, streaming events to `onUpdate`. */
export async function followJob(id: string, onUpdate: (j: JobView) => void, signal?: { stop: boolean }): Promise<JobView> {
  let since = 0;
  let events: JobView["events"] = [];
  for (;;) {
    if (signal?.stop) throw new Error("cancelled");
    const j = await api.job(id, since);
    events = events.concat(j.events);
    since = j.n_events;
    const full = { ...j, events };
    onUpdate(full);
    if (j.status === "done" || j.status === "error") return full;
    await new Promise((r) => setTimeout(r, 280));
  }
}
