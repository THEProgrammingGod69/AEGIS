/** Turns engine findings into technician instructions: what to do, where, and roughly how long it takes. */
import { COLOUR_NAME } from "./format";
import type { Item, RunPayload } from "./types";

export interface Fix {
  action: string;
  detail: string;
  where: string;
  minutes: number;
  kind: "fix" | "rephoto" | "review";
}

const colour = (c: string) => `${COLOUR_NAME[c] ?? c} (${c})`;

function where(it: Item, p: RunPayload): string {
  if ((p.engine_kind ?? p.meta.engine_kind) === "real") return it.view ? `${it.view} drawing view · ${it.target}` : `Drawing target: ${it.target}`;
  const [x, y] = it.box;
  const at = `${Math.round(x)} mm across, ${Math.round(y)} mm down`;
  if (it.check === "ORDER") return `${it.target}, slots 1–${it.slots?.length ?? "?"}`;
  if (it.check === "FERRULE" || it.check === "COLOUR") {
    const [strip, pos] = it.target.split(":");
    return `Terminal strip ${strip}, position ${pos} · ${at}`;
  }
  const rail = p.rails.find((r) => r.tags.includes(it.target));
  return rail ? `${rail.name}, slot ${rail.tags.indexOf(it.target) + 1} · ${at}` : at;
}

export function fixFor(it: Item, p: RunPayload): Fix {
  if (it.check === "REGISTRATION" || it.id === "REG-DRAWING") return { action: "Match the cabinet photograph to its drawing", detail: "Verify the cabinet identity and drawing revision, then start a new inspection with a clear relevant cabinet view. A new photo alone cannot correct an unrelated drawing.", where: "Inspection inputs", minutes: 2, kind: "rephoto" };
  const w = where(it, p);
  if (it.result === "REVIEW") {
    const documentation = it.id.startsWith("DOC-") || (it.rule ?? "").endsWith(".unsupported_input");
    return { action: documentation ? `Review ${it.target} manually` : `Resolve evidence for ${it.target}`,
      detail: it.hint || (documentation ? "Compare the uploaded requirements with the cabinet and record a manual inspection. This document is not automatically verified."
        : "Review the drawing and photo evidence. Confirm matching inputs and capture additional detail when needed before deciding."),
      where: documentation ? "Uploaded inspection requirements" : w, minutes: 2, kind: "review" };
  }
  switch (it.check) {
    case "GA":
      return { action: `Install ${it.target}`, detail: `The drawing places ${it.target} here and the slot is empty. Mount it as drawn on the GA and wire it per the wire list.`, where: w, minutes: 15, kind: "fix" };
    case "ORDER": {
      const s = it.swaps?.[0];
      return s
        ? { action: `Swap ${s[0]} and ${s[1]}`, detail: `On ${it.target} the two devices sit in each other's positions. Drawing order: ${it.expected.replace(/-/g, " · ")}.`, where: w, minutes: 10, kind: "fix" }
        : { action: `Re-seat ${it.target} in drawing order`, detail: `Read on the rail: ${it.found}. Drawing order: ${it.expected.replace(/-/g, " · ")}.`, where: w, minutes: 12, kind: "fix" };
    }
    case "LABEL":
      return it.found.startsWith("Wrong")
        ? { action: `Replace the label on ${it.target}`, detail: `${it.found.replace("Wrong label: ", "The label ")}. Print and apply “${it.expected}”.`, where: w, minutes: 4, kind: "fix" }
        : { action: `Apply label “${it.expected}”`, detail: `No label was found on ${it.target}. Print it from the label list and apply it where the drawing shows it.`, where: w, minutes: 3, kind: "fix" };
    case "FERRULE":
      return it.found === "No ferrule"
        ? { action: `Fit ferrule “${it.expected}”`, detail: `The wire on terminal ${it.target} has no marker sleeve. Slide on the sleeve printed ${it.expected}.`, where: w, minutes: 5, kind: "fix" }
        : { action: `Replace ferrule on ${it.target}`, detail: `The sleeve reads ${it.found.replace("Wrong ferrule: ", "")}; the wire list says ${it.expected}. Check the wire is on the right terminal, then re-sleeve.`, where: w, minutes: 6, kind: "fix" };
    case "COLOUR":
      return { action: `Re-wire ${it.target} in ${COLOUR_NAME[it.expected] ?? it.expected}`, detail: `Found ${colour(it.found)}, the wire list says ${colour(it.expected)}. Replace the conductor with the specified colour.`, where: w, minutes: 12, kind: "fix" };
  }
  return { action: `Correct ${it.target}`, detail: `${it.found}; expected ${it.expected}.`, where: w, minutes: 5, kind: "fix" };
}
