import type { Item, Status } from "./types";

export const STATUS_COLOR: Record<Status | "HOLD", string> = {
  PASS: "var(--pass)",
  FAIL: "var(--fail)",
  REVIEW: "var(--review)",
  SKIP: "var(--skip)",
  CLOSED: "var(--closed)",
  OPEN: "var(--open)",
  REGRESSION: "var(--regression)",
  NEW: "var(--new)",
  HOLD: "var(--fail)",
};

export const STATUS_HEX: Record<Status, string> = {
  PASS: "#34d399",
  FAIL: "#fb7185",
  REVIEW: "#fbbf24",
  SKIP: "#94a3b8",
  CLOSED: "#34d399",
  OPEN: "#fb7185",
  REGRESSION: "#c084fc",
  NEW: "#fb923c",
};

export const CHECK_TITLE: Record<string, string> = {
  GA: "Part present",
  ORDER: "Rail order",
  LABEL: "Device label",
  FERRULE: "Ferrule text",
  COLOUR: "Wire colour",
};

export const COLOUR_NAME: Record<string, string> = {
  BN: "Brown",
  BU: "Blue",
  RD: "Red",
  BK: "Black",
  GNYE: "Green-yellow",
  GY: "Grey",
  VT: "Violet",
  "?": "Unclear",
};

export const COLOUR_HEX: Record<string, string> = {
  BN: "#7a4320",
  BU: "#1e50be",
  RD: "#c81e1e",
  BK: "#191919",
  GNYE: "linear-gradient(90deg,#28a03c 0 50%,#e1cd1e 50% 100%)",
  GY: "#969696",
  VT: "#8232a0",
};

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

/** Human explanation of why the engine decided what it decided for an item. */
export function explain(it: Item): string {
  const ev = it.evidence.join("; ");
  switch (it.check) {
    case "GA":
      if (it.result === "FAIL")
        return `The drawing places ${it.target} here. The slot looks like empty backplate (${ev}), so two independent signals agree: the part is missing.`;
      if (it.result === "REVIEW")
        return `The slot is partly occupied and the evidence disagrees, so EAGLE EYE asks for a re-photo of this zone instead of guessing.`;
      return `Slot occupancy matches an installed part (${ev}).`;
    case "ORDER":
      if (it.result === "FAIL")
        return `Labels were read slot by slot along ${it.target} and aligned with the drawing's sequence: ${it.found}.`;
      if (it.result === "REVIEW") return `At least one slot label on ${it.target} could not be read, so the order is sent to REVIEW.`;
      return `Every slot on ${it.target} holds the device the drawing puts there.`;
    case "LABEL":
      if (it.result === "SKIP") return `Not checked on its own: the root cause is already reported by ${it.root_cause ?? "another item"}.`;
      if (it.result === "FAIL" && it.found.startsWith("Wrong"))
        return `The label is present and every OCR vote agrees on a string that is not ${it.expected}.`;
      if (it.result === "FAIL") return `No sticker with print was found where the drawing prints ${it.expected}, and OCR read nothing.`;
      if (it.result === "REVIEW") return `A label is there but the votes do not agree, so this zone needs a sharper photo.`;
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
