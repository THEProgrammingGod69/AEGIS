/** NOT_IN_VIEW: the real-cabinet engine could not see the item in this photo (neither passed nor failed). */
export type Result = "PASS" | "FAIL" | "REVIEW" | "SKIP" | "NOT_IN_VIEW";
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
  /** calibrated probability that this verdict is right (PASS/FAIL) or that the item is faulty (REVIEW) */
  confidence?: number | null;
  /* wire colour by circuit class (real-cabinet COLOUR items) */
  colour?: string;
  allowed?: string[];
  wire_class?: WireClass | null;
  rule_source?: string | null;
  /* real-cabinet engine */
  view?: string | null;
  hint?: string | null;
  rule?: string | null;
  candidate?: string;
  strength?: "strong" | "weak" | null;
  reads?: { raw: string; tag: string | null; conf: number; passes: number; box: number[]; method?: string | null }[];
  agent?: AgentDecision | null;
  verified_by?: string[];
}

export interface AgentDecision {
  decision: "CONFIRMED_OK" | "CONFIRMED_FAULT" | "UNCLEAR";
  confidence: number;
  reason: string;
  model: string | null;
  cached: boolean;
  source?: string;
  rephoto_hint?: string | null;
}

export interface Coverage {
  in_view: number;
  verified: number;
  total: number;
  ratio: number;
  by_view: Record<string, { verified: number; total: number }>;
  complete?: boolean;
  approval_allowed?: boolean;
  unresolved?: number;
}

/** What is kept of a photo instead of the photo (metadata-first storage). */
export interface PhotoMeta {
  sha256?: string;
  sha?: string;
  size: [number, number];
  name?: string | null;
  bytes?: number;
  exif_orientation?: number;
}

export interface Counts {
  PASS: number;
  FAIL: number;
  REVIEW: number;
  SKIP: number;
  NOT_IN_VIEW?: number;
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
  ocr?: number;
  agent?: number;
}

export interface RunMeta {
  id: string;
  created: string;
  label: string;
  source: "upload" | "sample" | "forge" | "preset";
  photo_name: string;
  photo: string;
  inputs: { ga: InputRef; wires: InputRef; checklist: InputRef };
  enabled: string[];
  cabinet: string;
  counts: Counts;
  items: number;
  verdict: Verdict;
  timing: Timing;
  registration: { anchors: number; inliers: number; outliers: string[]; refined: boolean; targets: number; valid?: boolean; localised?: boolean; invalid_reason?: string | null; fits?: { view: string }[]; views?: string[] };
  issues: {
    id: string; result: Result; found: string; marker: number; recheck?: Recheck;
    /** where the finding belongs on the assembly line (runs saved since the fault Pareto) */
    check?: string; target?: string; family?: string; area?: string; station?: string; confidence?: number | null;
  }[];
  confidence?: PhotoConfidence | null;
  parent: string | null;
  root: string;
  version: number;
  recheck: RecheckCounts | null;
  forge?: { seed: number; strength: number; faults: ForgeFault[]; score: ForgeScore };
  engine: string;
  warnings?: { code: string; message: string }[];
  /** Inspector decisions (human in the loop), keyed by item id. */
  reviews?: Record<string, Review>;
  /** Where the run came from in the hosted console: recorded showcase or the live cloud engine. */
  origin?: "recorded" | "cloud" | "local";
  engine_kind?: "legacy" | "real";
  storage?: "metadata";
  photo_meta?: PhotoMeta;
  cached?: boolean;
  /** Historical evidence was invalid; regenerate exports with a new inspection. */
  historical_guard?: boolean;
  coverage?: Coverage;
  views?: string[];
  agent?: { enabled: boolean; backend: string | null; model: string | null; calls: number; cost_usd: number; reason?: string };
}

export interface Review {
  decision: "PASS" | "FAIL";
  note: string;
  by: string;
  at: string;
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
    valid?: boolean;
    localised?: boolean;
    invalid_reason?: string | null;
    fits?: { view: string; model?: string; angle?: ViewAngle | null }[];
    views?: string[];
    /** viewing angle of the camera measured from the fitted perspective (real cabinet) */
    angle?: ViewAngle | null;
  };
  photo_size: [number, number];
  size_mm: [number, number];
  backplate_quad: Pt[];
  rails: { name: string; tags: string[] }[];
  wires: { terminal: string; ferrule: string; colour: string }[];
  timing: Timing;
  /** Raster of a custom GA drawing (cloud runs); the demo drawing's raster ships with the console. */
  ga_raster?: { w: number; h: number; ox: number; oy: number; k: number };
  /** false for real-cabinet runs: there is no drawing-aligned view of the photo. */
  rectified?: boolean;
  engine_kind?: "legacy" | "real";
  coverage?: Coverage;
  views?: string[];
  agent?: { enabled: boolean; backend: string | null; model: string | null; calls: number; cost_usd: number; summary?: string; reason?: string };
  ocr?: { engine: string; tokens: number; seconds: number | null; cached: boolean; mode: string };
  quality?: { blur: number; brightness: number; glare: number; score: number; issues: string[] };
  notes?: string[];
  photo_meta?: PhotoMeta;
  /** where this run's wire-colour rule came from and what it allows per circuit class */
  wire_rule?: WireRule | null;
  /** real cabinet: how the straightened photo (rectified.jpg) maps to the photo */
  rectify?: { view: string; H: number[][]; k: number; origin: [number, number]; size: [number, number]; angle?: ViewAngle | null } | null;
}

export interface ViewAngle { tilt: number; yaw: number; pitch: number; focal_px: number; focal_source: "estimated" | "assumed" | "given" }

export type WireClass = "AC" | "DC" | "ALARM" | "PE";

export interface WireRule {
  source: string | null;
  kind: "legend" | "profile" | "wire_list" | null;
  profile?: string | null;
  classes: Partial<Record<WireClass, string[]>>;
  notes: string[];
  universal?: string;
  /** circuit classes inferred from the drawing's wiring */
  circuits?: { wires: number; classified: Partial<Record<WireClass, number>>; conflicts: number };
  ferrules?: number;
  judged?: number;
  not_measured?: number;
  no_rule?: number;
  /** wire-list rule: number of wires with their own colour */
  wires?: number;
}

export interface Preset {
  id: string;
  title: string;
  cabinet: string | null;
  ga: string;
  photos: { file: string; content: string }[];
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
  /** Hosted console: "cloud" = real engine run, "recorded" = replay of a recorded run. */
  mode?: "cloud" | "recorded" | "local";
  note?: string;
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
  tesseract: { ok: boolean; cmd: string; version: string | null; error?: string; backend?: string };
  workers: number;
  cpu: number;
  checks: string[];
  runs: number;
  mode?: "local" | "cloud" | "recorded";
  uptime?: number;
  busy?: number;
  ocr?: { engine: string; version: string | null; ok: boolean; fallback: string | null; mode?: string; workers?: number };
  agent?: { enabled: boolean; backend: string | null; model: string; fast_model: string; reason: string };
  presets?: { id: string; title: string; photos: number }[];
  storage?: "metadata";
}

export interface CheckInfo {
  name: string;
  title: string;
  question: string;
  doc: string;
  builtin: boolean;
}

/** Fault Forge, synthetic vs real (eval_gap.py): planted faults scored the same way on both kinds of photo. */
export type GapOutcome = "FAIL" | "REVIEW" | "PASS" | "unassessed";
export interface GapCategory {
  planted: number;
  FAIL: number;
  REVIEW: number;
  PASS: number;
  unassessed: number;
  fail_rate: number;
  flag_rate: number;
  incorrect_pass_rate: number;
}
export interface GapSide {
  photos: number;
  planted: number;
  FAIL: number;
  REVIEW: number;
  PASS: number;
  unassessed: number;
  fail_rate: number;
  flag_rate: number;
  incorrect_pass_rate: number;
  false_fail: number;
  false_fail_rate: number;
  review_rate: number;
  not_in_view_rate: number;
  judged: number;
  sec_per_photo: number | null;
  categories: Record<string, GapCategory>;
  engine: string;
  source: string;
  selection: string;
  agent?: string;
  /** real side only: photos of the cabinet, or renders of its GA drawing (render_real.py) */
  kind?: "photo" | "drawing_render";
}
export type GapRate = "fail_rate" | "flag_rate" | "incorrect_pass_rate" | "false_fail_rate" | "review_rate" | "not_in_view_rate";
export interface ForgeGap {
  schema: string;
  created: string;
  engine: string;
  synthetic: GapSide | null;
  real: GapSide | null;
  real_reason: string | null;
  gap: Record<GapRate, number> | null;
  categories: { id: string; label: string; synthetic: GapCategory | null; real: GapCategory | null }[];
  real_rows: { photo: string; faults: { category: string; type: string; text?: string; outcome: GapOutcome }[]; false_fail: number }[];
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

export interface EvaluationDataset {
  id: "synthetic" | "real";
  label: string;
  source: "synthetic" | "real";
  status: "available" | "legacy" | "not_evaluated";
  images: number | null;
  cabinets: number | null;
  engine_version: string | null;
  confirmed: number | null;
  referred: number | null;
  incorrect_pass: number | null;
  unassessed: number | null;
  total_faults: number | null;
  review_rate: number | null;
  false_fail: number | null;
  note: string;
}

export interface Evaluation {
  schema: string;
  metrics: Record<string, string>;
  datasets: EvaluationDataset[];
}

/** Per-photo confidence: mean calibrated confidence of its PASS/FAIL verdicts (calibration.py). */
export interface PhotoConfidence {
  score: number;
  decided: number;
  expected_errors: number;
  review: number;
  lowest: { id: string; result: Result; confidence: number }[];
}

/** Confidence calibration from Fault Forge runs (out/forge/calibration.json). */
export interface CalBin { lo: number; hi: number; n: number; k: number; p: number }
export interface CurvePoint { lo: number; hi: number; n: number; stated: number; observed: number }
export interface CalEngine {
  label: string;
  images: number;
  items: number;
  checks?: string[];
  /** kinds of measurement the fit saw ("text", "colour"); items of other kinds have no calibrated confidence */
  measures?: string[];
  counts: Record<"PASS" | "FAIL" | "REVIEW", number>;
  maps: Partial<Record<"PASS" | "FAIL" | "REVIEW", CalBin[]>>;
  heldout: { items: number; accuracy: number | null; ece_raw: number | null; ece_cal: number | null; raw: CurvePoint[]; cal: CurvePoint[] };
  review: { n: number; fault_rate: number | null };
}
export interface Calibration {
  schema: string;
  created: string;
  engine_version: string;
  method: string;
  engines: Partial<Record<"demo" | "real", CalEngine>>;
}
