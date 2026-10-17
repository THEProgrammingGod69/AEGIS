import { staticApi, staticUrl } from "./static";
import type { CheckInfo, ForgeLive, Health, JobView, RunMeta, RunPayload, Sample, SelfTest } from "./types";

/** True in the hosted showcase build (npm run build:static): recorded runs, no live engine. */
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
}

const liveApi = {
  health: () => req<Health>("/api/health"),
  checks: () => req<CheckInfo[]>("/api/checks"),
  samples: () => req<Sample[]>("/api/samples"),
  inputs: () => req<Record<string, { name: string; size: number }>>("/api/inputs"),
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
    else if (i.sample) fd.append("sample", i.sample);
    if (i.ga) fd.append("ga", i.ga);
    if (i.wires) fd.append("wires", i.wires);
    if (i.checklist) fd.append("checklist", i.checklist);
    if (i.checks) fd.append("checks", i.checks.join(","));
    if (i.parent) fd.append("parent", i.parent);
    return req<JobView>("/api/inspect", { method: "POST", body: fd });
  },
};

const liveUrl = {
  sample: (id: string, w = 0) => `/api/samples/${id}/image${w ? `?w=${w}` : ""}`,
  file: (run: string, name: string, w = 0) => `/api/runs/${run}/files/${name}${w ? `?w=${w}` : ""}`,
  download: (run: string, name: string) => `/api/runs/${run}/files/${name}?download=1`,
  crop: (run: string, item: string, kind: "expected" | "found" | "aligned") =>
    `/api/runs/${run}/items/${encodeURIComponent(item)}/${kind}`,
  input: (key: string) => `/api/inputs/${key}`,
  gaPreview: () => "/api/inputs/ga/preview",
};

export const api: typeof liveApi = STATIC ? (staticApi as unknown as typeof liveApi) : liveApi;
export const url: typeof liveUrl = STATIC ? (staticUrl as unknown as typeof liveUrl) : liveUrl;

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
