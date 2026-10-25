import type { CSSProperties } from "react";
import type { Item, Status } from "./types";

export const STATUS_COLOR: Record<Status | "HOLD", string> = {
  PASS: "var(--pass)",
  FAIL: "var(--fail)",
  REVIEW: "var(--review)",
  SKIP: "var(--skip)",
  NOT_IN_VIEW: "var(--niv)",
  CLOSED: "var(--closed)",
  OPEN: "var(--open)",
  REGRESSION: "var(--regression)",
  NEW: "var(--new)",
  HOLD: "var(--fail)",
};

/** Overlay colours for boxes drawn on photos: always inside a dark device panel, so the signal palette. */
export const STATUS_HEX: Record<Status, string> = {
  PASS: "#2bd49a",
  FAIL: "#ff5468",
  REVIEW: "#ffb547",
  SKIP: "#94a3b8",
  NOT_IN_VIEW: "#7d8794",
  CLOSED: "#2bd49a",
  OPEN: "#ff5468",
  REGRESSION: "#a78bfa",
  NEW: "#fb923c",
};

/** Fills for a text colour: REVIEW's text amber is too dark to fill a bar, dot or marker with on the light canvas,
 *  so its fills use the bright bar amber (and dark ink on top). Every other colour fills with itself. */
const FILL: Record<string, [fill: string, ink: string]> = { "var(--review)": ["var(--review-bar)", "#3d2600"] };

/** Inline colour variables for a coloured element: --c for its text, --cf for its fills, tints and glows, --ci for
 *  text set on that fill. Set all three wherever --c is set, so a nested element never inherits a parent's fill. */
export function tone(c: string): CSSProperties {
  const [f, i] = FILL[c] ?? [c, "#fff"];
  return { ["--c" as string]: c, ["--cf" as string]: f, ["--ci" as string]: i } as CSSProperties;
}

/** Solid fill for a status (chart bars and segments). */
export const statusFill = (s: Status | "HOLD") => (FILL[STATUS_COLOR[s]]?.[0] ?? STATUS_COLOR[s]);

export const CHECK_TITLE: Record<string, string> = {
  GA: "Part present",
  MISSING: "Part present",
  UNKNOWN_LABEL: "Unknown label",
  ORDER: "Rail order",
  LABEL: "Device label",
  FERRULE: "Ferrule text",
  COLOUR: "Wire colour",
  REGISTRATION: "Drawing alignment",
};

export const COLOUR_NAME: Record<string, string> = {
  BK: "Black", BN: "Brown", RD: "Red", OG: "Orange", YE: "Yellow", GN: "Green", BU: "Blue", VT: "Violet", GY: "Grey",
  WH: "White", PK: "Pink", TQ: "Turquoise", GNYE: "Green-yellow", "GN/YE": "Green-and-yellow", "WH/BU": "White, blue stripe",
  "?": "Unclear",
};

const GNYE_HEX = "linear-gradient(90deg,#28a03c 0 50%,#e1cd1e 50% 100%)";
export const COLOUR_HEX: Record<string, string> = {
  BK: "#191919", BN: "#7a4320", RD: "#c81e1e", OG: "#ee7a1a", YE: "#e8cc1e", GN: "#1f8f45", BU: "#1e50be", VT: "#8232a0",
  GY: "#969696", WH: "#f1f1ec", PK: "#f09ab2", TQ: "#22b0bc", GNYE: GNYE_HEX, "GN/YE": GNYE_HEX,
  "WH/BU": "linear-gradient(180deg,#f1f1ec 0 38%,#1e50be 38% 62%,#f1f1ec 62% 100%)",
};

export const WIRE_CLASS_NAME: Record<string, string> = { AC: "AC mains", DC: "DC distribution", ALARM: "Alarm wiring", PE: "Protective earth" };
/** The class name inside a sentence ("AC mains", "alarm wiring"). */
export const wireClassPhrase = (c: string) => (c === "AC" || c === "DC" ? WIRE_CLASS_NAME[c] : (WIRE_CLASS_NAME[c] ?? c).toLowerCase());

/** Status shown for an item: its re-check status when the run is a re-check. */
export function statusOf(it: Item): Status {
  return it.recheck ?? it.result;
}

export function isIssue(it: Item) {
  return it.marker != null && (it.recheck != null || it.result === "FAIL" || it.result === "REVIEW");
}

export function runTime(id: string) {
  const m = id.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
  if (!m) return id;
  return `${m[4]}:${m[5]}:${m[6]}`;
}

export function runDate(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function shortId(id: string) {
  return id.slice(-4).toUpperCase();
}

export function plural(n: number, w: string, p?: string) {
  return `${n} ${n === 1 ? w : p ?? w + "s"}`;
}

/** Short label for a status chip (NOT_IN_VIEW reads better with spaces). */
export const statusText = (s: string) => (s === "NOT_IN_VIEW" ? "NOT IN VIEW" : s);

/** Explain only evidence actually recorded for this item. */
function explainReal(it: Item): string {
  const ev = it.evidence.filter((e) => !e.startsWith("Claude:")).join("; ");
  const agent = it.agent ? ` Recorded verifier (${it.agent.model ?? "model"}): ${it.agent.reason}` : "";
  if (it.result === "NOT_IN_VIEW") return `Not judged: this photo does not show ${it.target} clearly enough (${ev}). It is neither passed nor failed.`;
  if (it.result === "SKIP") return `Not judged on its own: ${it.root_cause ? `the root cause is reported by ${it.root_cause}` : ev}.`;
  if (it.result === "FAIL") return `The recorded visual evidence supports a defect against the drawing: ${ev}.${agent}`;
  if (it.result === "REVIEW") return `The available evidence does not establish PASS or FAIL: ${ev}.${agent}${it.hint ? ` Next action: ${it.hint}.` : " Inspect this item or capture clearer evidence."}`;
  return `Verified by ${(it.verified_by ?? []).join(" + ") || "OCR"} against the drawing: ${ev}.${agent}`;
}

/** Human explanation of why the engine decided what it decided for an item. */
export function explain(it: Item): string {
  const ev = it.evidence.join("; ");
  if (it.check === "REGISTRATION" || it.id === "REG-DRAWING") return `Inspection is blocked because the photo cannot be reliably placed on the drawing. ${ev} This is one input or alignment problem, rather than evidence of separate component defects.`;
  if (it.result === "SKIP") return `Not evaluated on its own${it.root_cause ? `: resolve ${it.root_cause} first` : ": this check was skipped"}. ${ev}`;
  if (it.result === "NOT_IN_VIEW") return `This required item is not visible enough in this photograph to judge. Capture the relevant cabinet view; it has neither passed nor failed. ${ev}`;
  if (it.check === "COLOUR" && it.colour) {
    const seen = `${COLOUR_NAME[it.colour] ?? it.colour} after white balance`;
    const cls = it.wire_class ? wireClassPhrase(it.wire_class) : "its circuit";
    const rule = it.rule_source ?? "the universal rule (green-and-yellow for protective earth only)";
    if (it.result === "PASS") return `The wire beside ferrule ${it.target} reads ${seen}; ${rule} allows it for ${cls}.`;
    return `The wire beside ferrule ${it.target} reads ${seen}, which ${rule} does not allow for ${cls}. A colour measured in a photo never fails a cabinet on its own, so a person confirms it. ${ev}`;
  }
  if (it.verified_by !== undefined || it.check === "MISSING" || it.check === "UNKNOWN_LABEL") return explainReal(it);
  switch (it.check) {
    case "GA":
      if (it.result === "FAIL")
        return `The drawing places ${it.target} here. The matched slot has evidence of empty backplate (${ev}), supporting a missing-part finding.`;
      if (it.result === "REVIEW")
        return `The slot is partly occupied and the evidence disagrees, so EAGLE EYE asks for a re-photo of this zone instead of guessing.`;
      return `Slot occupancy matches an installed part (${ev}).`;
    case "ORDER":
      if (it.result === "FAIL")
        return `Labels were read slot by slot along ${it.target} and aligned with the drawing's sequence: ${it.found}.`;
      if (it.result === "REVIEW") return `At least one slot label on ${it.target} could not be read, so the order is sent to REVIEW.`;
      return `Every slot on ${it.target} holds the device the drawing puts there.`;
    case "LABEL":
      if (it.result === "FAIL" && it.found.startsWith("Wrong"))
        return `The label is present and every OCR vote agrees on a string that is not ${it.expected}.`;
      if (it.result === "FAIL") return `No sticker with print was found where the drawing prints ${it.expected}, and OCR read nothing.`;
      if (it.result === "REVIEW") return `The expected label was not reliably read. Check drawing alignment, visibility and image detail before deciding whether it is incorrect or missing. ${ev}`;
      return `OCR votes decoded against the drawing's closed vocabulary agree on ${it.expected}.`;
    case "FERRULE":
      if (it.result === "FAIL" && it.found === "No ferrule") return `No white sleeve pixels where the ferrule on ${it.target} should be (${ev}).`;
      if (it.result === "FAIL") return `The sleeve reads another wire-list string (${it.found.replace("Wrong ferrule: ", "")}) instead of ${it.expected}.`;
      if (it.result === "REVIEW") return `The sleeve is there but its text could not be decoded against the wire list.`;
      return `Sleeve text decoded against the wire list (not free OCR) matches ${it.expected}.`;
    case "COLOUR":
      if (it.result === "FAIL")
        return `After white-balancing on the white labels, the wire at ${it.target} reads ${COLOUR_NAME[it.found] ?? it.found}, but the wire list says ${COLOUR_NAME[it.expected] ?? it.expected}.`;
      if (it.result === "REVIEW") return `The colour sample is ambiguous under this light; re-photo the zone.`;
      return `Colour after white balance matches the wire list (${COLOUR_NAME[it.expected] ?? it.expected}).`;
  }
  return ev;
}
