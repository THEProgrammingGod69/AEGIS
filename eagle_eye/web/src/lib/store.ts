/**
 * Browser-side run store for the hosted console (IndexedDB). Cloud inspections live here: the engine keeps
 * nothing, so the history, re-check chains and downloads survive a reload on this device.
 * Falls back to memory when IndexedDB is unavailable (private windows, locked-down browsers).
 */
import type { JobEvent, RunMeta, RunPayload } from "./types";

export type InputKey = "ga" | "wires" | "checklist";

export interface LiveRun {
  id: string;
  meta: RunMeta;
  payload: RunPayload;
  report: unknown;
  events: JobEvent[];
  files: Record<string, Blob>;
  /** Custom drawing set uploaded with the run, re-sent when the run is re-checked. */
  inputs?: Partial<Record<InputKey, { name: string; blob: Blob }>>;
  /** Restore the same preset drawing after the stateless engine's input cache is cleared. */
  preset?: string;
  engine?: "legacy" | "real";
  saved: number;
}

const DB = "eagle-eye";
const STORE = "runs";
let dbp: Promise<IDBDatabase | null> | null = null;
const memory = new Map<string, LiveRun>();

function open(): Promise<IDBDatabase | null> {
  if (dbp) return dbp;
  dbp = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbp;
}

function tx<T>(db: IDBDatabase, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const r = fn(t.objectStore(STORE));
    t.oncomplete = () => resolve(r ? r.result : undefined);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

export async function loadAll(): Promise<LiveRun[]> {
  const db = await open();
  if (!db) return [...memory.values()];
  try {
    return ((await tx<LiveRun[]>(db, "readonly", (s) => s.getAll())) ?? []).sort((a, b) => a.saved - b.saved);
  } catch {
    return [...memory.values()];
  }
}

export async function put(run: LiveRun) {
  memory.set(run.id, run);
  const db = await open();
  if (!db) return;
  try {
    await tx(db, "readwrite", (s) => s.put(run));
  } catch {
    /* quota or private mode: the run stays in memory for this session */
  }
}

export async function remove(ids: string[]) {
  ids.forEach((id) => memory.delete(id));
  const db = await open();
  if (!db) return;
  try {
    await tx(db, "readwrite", (s) => { ids.forEach((id) => s.delete(id)); });
  } catch {
    /* ignore */
  }
}

export async function clearAll() {
  memory.clear();
  const db = await open();
  if (!db) return;
  try {
    await tx(db, "readwrite", (s) => s.clear());
  } catch {
    /* ignore */
  }
}
