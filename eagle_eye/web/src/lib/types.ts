export type Result = "PASS" | "FAIL" | "REVIEW" | "SKIP";
export type Recheck = "CLOSED" | "OPEN" | "REGRESSION" | "NEW";
export type Status = Result | Recheck;
export type Pt = [number, number];
export type Box = [number, number, number, number];

export interface Slot {
  slot: number;
  expected: string;
  read: string;
  box: Box;
}

export interface Item {
  id: string;
  check: string;
  target: string;
  expected: string;
  found: string;
  result: Result;
  box: Box;
  conf: number;
  evidence: string[];
  quad: Pt[];
  marker?: number | null;
  recheck?: Recheck;
  prev_result?: Result;
  prev_found?: string;
  slots?: Slot[];
  swaps?: [string, string][];
  swatch?: string;
  votes?: string[];
  occupancy?: number;
  root_cause?: string;
}

export interface Counts {
  PASS: number;
  FAIL: number;
  REVIEW: number;
  SKIP: number;
}

export interface RecheckCounts {
  CLOSED: number;
  OPEN: number;
  REGRESSION: number;
  NEW: number;
}

export interface Verdict {
  label: "PASS" | "HOLD" | "REVIEW";
  headline: string;
  detail: string;
}

export interface InputRef {
  path: string;
  name: string;
  demo: boolean;
}

export interface ForgeFault {
  type: string;
  [k: string]: string | number;
}

export interface ForgeScore {
  planted: { fault: ForgeFault; text: string; item: string; caught: boolean; result: Result | null; found: string | null }[];
  caught: number;
  n_planted: number;
  false_alarms: string[];
  reviews: string[];
  correct_items: number;
}

export interface Timing {
  parse: number;
  register: number;
  checks: Record<string, number>;
  total: number;
  report?: number;
}

export interface RunMeta {
  id: string;
  created: string;
  label: string;
  source: "upload" | "sample" | "forge";
  photo_name: string;
  photo: string;
  inputs: { ga: InputRef; wires: InputRef; checklist: InputRef };
  enabled: string[];
  cabinet: string;
  counts: Counts;
  items: number;
  verdict: Verdict;
  timing: Timing;
  registration: { anchors: number; inliers: number; outliers: string[]; refined: boolean; targets: number };
  issues: { id: string; result: Result; found: string; marker: number; recheck?: Recheck }[];
  parent: string | null;
  root: string;
  version: number;
  recheck: RecheckCounts | null;
  forge?: { seed: number; strength: number; faults: ForgeFault[]; score: ForgeScore };
  engine: string;
  warnings?: { code: string; message: string }[];
}

export interface AnchorPoint {
  tag: string;
  kind: "label" | "ferrule";
  inlier: boolean | null;
  found_px: Pt;
  expected_px: Pt;
  found_mm: Pt;
  expected_mm: Pt;
  residual_mm: number;
}

export interface LayoutItem {
  tag: string;
  kind: string;
  box: Box;
  quad: Pt[];
  label_box?: Box;
}

export interface RunPayload {
  meta: RunMeta;
  results: Item[];
  layout: LayoutItem[];
  registration: {
    quad: Pt[];
    anchors: number;
    inliers: number;
    outliers: string[];
    refined: boolean;
    targets: number;
    anchor_points: AnchorPoint[];
  };
  photo_size: [number, number];
  size_mm: [number, number];
  backplate_quad: Pt[];
  rails: { name: string; tags: string[] }[];
  wires: { terminal: string; ferrule: string; colour: string }[];
  timing: Timing;
}

export interface JobEvent {
  stage: string;
  status: "start" | "done";
  t: number;
  [k: string]: unknown;
}

export interface JobView {
  id: string;
  kind: "inspect" | "recheck" | "forge";
  status: "queued" | "running" | "done" | "error";
  events: JobEvent[];
  n_events: number;
  runs: string[];
  run_id: string | null;
  error: string | null;
  label?: string;
  parent?: string | null;
  count?: number;
  queue_position: number;
  elapsed: number;
}

export interface Sample {
  id: string;
  file: string;
  title: string;
  subtitle: string;
  expect: string;
  counts: Counts;
  issues: { id: string; result: Result; found: string }[];
  fault_text: string[];
}

export interface Health {
  ok: boolean;
  version: string;
  tesseract: { ok: boolean; cmd: string; version: string | null; error?: string };
  workers: number;
  cpu: number;
  checks: string[];
  runs: number;
}

export interface CheckInfo {
  name: string;
  title: string;
  question: string;
  doc: string;
  builtin: boolean;
}

export interface SelfTest {
  summary: {
    cabinets: number;
    planted: number;
    caught: number;
    recall: number;
    correct_items: number;
    false_alarms: number;
    reviews: number;
    review_rate: number;
    per_type: Record<string, [number, number]>;
    clean_cabinets: number;
    clean_cabinets_zero_fail: number;
    sec_per_cabinet: number | null;
    cpu_cores?: number;
  } | null;
  cabinets: {
    i: number;
    strength: number;
    planted: number;
    caught: number;
    false_alarms: number;
    reviews: number;
    anchors: number;
    sec: number | null;
    faults: string[];
  }[];
}

export interface ForgeLive {
  cabinets: number;
  planted: number;
  caught: number;
  false_alarms: number;
  reviews: number;
  correct_items: number;
  runs: { id: string; seed: number; created: string; planted: number; caught: number; false_alarms: number; reviews: number }[];
}
