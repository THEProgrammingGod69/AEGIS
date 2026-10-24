/**
 * Connection to the hosted EAGLE EYE engine (the same Python engine, in a container: /api/v2).
 *
 * The engine is stateless: one request inspects a photo and streams progress, then the complete run
 * (payload, report, photo, rectified image, marked photo, PDF, filled checklist) as NDJSON. The browser keeps
 * the runs (store.ts), so any container instance can serve any request.
 */
import { useSyncExternalStore } from "react";
import type { Health, JobEvent, RunPayload } from "./types";

export const ENGINE_URL = String(import.meta.env.VITE_ENGINE_URL ?? "").replace(/\/+$/, "");

export type EngineState = "off" | "checking" | "ready" | "down";
export interface EngineInfo {
  state: EngineState;
  health: Health | null;
  url: string;
  preferLive: boolean;
  checkedAt: number;
  latency: number | null;
}

const PREF_KEY = "ee_engine_pref";
function readPref() {
  try {
    return localStorage.getItem(PREF_KEY) !== "recorded";
  } catch {
    return true;
  }
}

let info: EngineInfo = { state: ENGINE_URL ? "checking" : "off", health: null, url: ENGINE_URL, preferLive: readPref(), checkedAt: 0, latency: null };
const subs = new Set<() => void>();
const set = (patch: Partial<EngineInfo>) => {
  info = { ...info, ...patch };
  subs.forEach((f) => f());
};

export const engine = () => info;
export const subscribeEngine = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};
export function useEngine() {
  return useSyncExternalStore(subscribeEngine, engine, engine);
}

/** Live inspections are possible: engine reachable and the viewer has not switched to recorded replays. */
export const liveReady = () => info.state === "ready" && info.preferLive;

export function setPreferLive(v: boolean) {
  try {
    localStorage.setItem(PREF_KEY, v ? "live" : "recorded");
  } catch {
    /* private window */
  }
  set({ preferLive: v });
  if (v && info.state === "down") void pingEngine();
}

let pending: Promise<boolean> | null = null;

/** Health check; the first one also wakes a cold container (can take a few seconds). */
export function pingEngine(timeoutMs = 45000): Promise<boolean> {
  if (!ENGINE_URL) return Promise.resolve(false);
  if (pending) return pending;
  if (info.state !== "ready") set({ state: "checking" });
  const t0 = performance.now();
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  pending = fetch(`${ENGINE_URL}/api/v2/health`, { signal: ctl.signal, cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((h: Health) => {
      const ok = !!h.ok;
      set({ state: ok ? "ready" : "down", health: h, checkedAt: Date.now(), latency: Math.round(performance.now() - t0) });
      return ok;
    })
    .catch(() => {
      set({ state: "down", checkedAt: Date.now(), latency: null });
      return false;
    })
    .finally(() => {
      clearTimeout(timer);
      pending = null;
    });
  return pending;
}

/** Wait for an in-flight health check (if any) and report whether live runs are possible. */
export async function ensureEngine(): Promise<boolean> {
  if (!ENGINE_URL) return false;
  if (info.state === "checking" || pending) await pingEngine();
  else if (info.state === "down" && Date.now() - info.checkedAt > 8000) await pingEngine(20000);
  return liveReady();
}

/** Keep the container warm while the console is open (a demo should never hit a cold start). */
export function startKeepAlive() {
  if (!ENGINE_URL) return;
  void pingEngine();
  setInterval(() => {
    if (document.visibilityState === "visible") void pingEngine(20000);
  }, 4 * 60 * 1000);
}

/* ---------------- streaming ---------------- */
export interface StreamResult {
  type: "result";
  payload: RunPayload;
  report: unknown;
  files: Record<string, string>;
}

export interface StreamHandlers {
  onEvent: (ev: JobEvent) => void;
  onQueued?: (position: number) => void;
  onResult: (r: StreamResult) => void | Promise<void>;
}

export class EngineUnreachable extends Error {}

/** POST to the engine and consume its NDJSON stream. Engine errors are thrown as Error(detail). */
export async function stream(path: string, init: RequestInit, h: StreamHandlers): Promise<void> {
  let res: Response;
  try {
    res = await fetch(ENGINE_URL + path, init);
  } catch (e) {
    set({ state: "down", checkedAt: Date.now() });
    throw new EngineUnreachable(`The cloud engine could not be reached (${(e as Error).message}).`);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const b = await res.json();
      if (b?.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* keep status */
    }
    if (res.status >= 500) throw new EngineUnreachable(`The cloud engine failed (${msg}).`);
    throw new Error(msg);
  }
  const results: StreamResult[] = [];
  const handle = (line: string) => {
    const m = JSON.parse(line);
    if (m.type === "event") h.onEvent(m.event);
    else if (m.type === "queued") h.onQueued?.(m.position);
    else if (m.type === "result") results.push(m);
    else if (m.type === "error") throw new Error(m.detail);
  };
  let got = false;
  if (res.body && "getReader" in res.body) {
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i: number;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (line) {
            handle(line);
            got = true;
          }
        }
        // results are handled as soon as they arrive so a multi-cabinet stream shows progress
        while (results.length) await h.onResult(results.shift()!);
      }
    } catch (e) {
      if (e instanceof SyntaxError || (e as Error).name === "TypeError") throw new EngineUnreachable("The connection to the cloud engine dropped mid-inspection.");
      throw e;
    }
    if (buf.trim()) handle(buf.trim());
  } else {
    for (const line of (await res.text()).split("\n")) if (line.trim()) { handle(line.trim()); got = true; }
  }
  while (results.length) await h.onResult(results.shift()!);
  if (!got) throw new EngineUnreachable("The cloud engine returned an empty response.");
}

/* ---------------- uploads ---------------- */
const MAX_SIDE = 2900;          // the engine's tuned photo size (service.prepare_photo)
const MAX_BYTES = 3.6 * 2 ** 20; // stay well under the platform's request body limit

/** Phone photos: apply EXIF rotation, shrink to the engine's working size, keep the upload small. */
export async function preparePhoto(f: File): Promise<File> {
  try {
    const bmp = await createImageBitmap(f, { imageOrientation: "from-image" } as ImageBitmapOptions);
    const big = Math.max(bmp.width, bmp.height) > MAX_SIDE;
    if (!big && f.size <= MAX_BYTES) {
      bmp.close();
      return f;
    }
    const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * k);
    c.height = Math.round(bmp.height * k);
    const g = c.getContext("2d")!;
    g.imageSmoothingQuality = "high";
    g.drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close();
    let q = 0.92;
    let blob: Blob | null = null;
    for (;;) {
      blob = await new Promise<Blob | null>((r) => c.toBlob(r, "image/jpeg", q));
      if (!blob || blob.size <= MAX_BYTES || q < 0.62) break;
      q -= 0.08;
    }
    if (!blob) return f;
    return new File([blob], f.name.replace(/\.[a-z0-9]+$/i, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return f;
  }
}

export function b64Blob(b64: string, type: string): Blob {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return new Blob([out], { type });
}
