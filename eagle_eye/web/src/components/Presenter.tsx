import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Mic, Play, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { go } from "../lib/router";

interface Step {
  title: string;
  say: string[];
  action: string;
  run: () => void | Promise<void>;
}

async function latest(pred: (m: { source: string; version: number }) => boolean = (m) => m.source !== "forge") {
  const runs = await api.runs(200);
  return runs.find(pred)?.id ?? runs[0]?.id ?? null;
}

const scrollTo = (id: string) => setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" }), 500);

/** The demo script, on screen: talking points per step and a button that performs the step. */
export const STEPS: Step[] = [
  {
    title: "The problem, the idea",
    say: ["Cabinet QC today: a person compares a photo with the GA drawing and a wire list, item by item.", "EAGLE EYE does not ask AI “what's wrong?”. It reads the drawing with code and checks every expected item at its known spot."],
    action: "Open the overview", run: () => go(""),
  },
  {
    title: "A live inspection",
    say: ["The real Python engine runs in the cloud: drawing parse, registration, five plug-in checks, consensus.", "About 2 seconds per cabinet on one CPU core, no GPU."],
    action: "Run sample 01 live", run: () => go("inspect/demo"),
  },
  {
    title: "Proof for every FAIL",
    say: ["4 FAIL: PS12 missing, CB43 ↔ CB44 swapped, 1CBP03 unlabelled, X3:3 without ferrule.", "Click the swap: the drawing crop next to the photo crop. Toggle Drawing and Anchors on the photo."],
    action: "Open the latest inspection", run: async () => { const id = await latest(); if (id) go(`run/${id}`); },
  },
  {
    title: "Work order for the technician",
    say: ["Every FAIL becomes a numbered fix with location, proof and a time estimate.", "Printable, with sign-off. Inspector overrides drop out automatically."],
    action: "Open its work order", run: async () => { const id = await latest(); if (id) go(`work/${id}`); },
  },
  {
    title: "Re-check after the fix",
    say: ["The technician fixes it and re-photographs. Pick sample 05.", "Fixed items CLOSE, the rest stay OPEN, new breakage is a REGRESSION. The history is kept as v1 → v2."],
    action: "Go to re-check", run: async () => { const id = await latest((m) => m.source !== "forge" && m.version === 1); if (id) { go(`run/${id}`); scrollTo("recheck"); } },
  },
  {
    title: "Human in the loop",
    say: ["When the engine is unsure it says REVIEW, never a guessed FAIL.", "An inspector decides with the proof on screen; every decision is logged with who and when."],
    action: "Open the review station", run: () => go("review"),
  },
  {
    title: "Cabinets it has never seen",
    say: ["Fault Forge builds a new cabinet, plants hidden faults, shoots it with a random camera.", "Ask the jury to guess, then reveal the answer key. Self-test: 87 / 87 caught, 0 false alarms on 1,950 correct items."],
    action: "Forge a cabinet", run: () => go("forge/run"),
  },
  {
    title: "Bad photos",
    say: ["Tilt, blur, glare, dim light, JPEG noise: the stress sweep makes the photo progressively worse.", "Findings move to REVIEW as quality drops; false FAILs stay at zero."],
    action: "Open the Robustness Lab", run: () => go("lab"),
  },
  {
    title: "QC analytics",
    say: ["Every run rolls up: first-pass yield, fix closure, inspector agreement.", "The heatmap shows where faults cluster on the cabinet, so the fix goes upstream."],
    action: "Open analytics", run: () => go("analytics"),
  },
  {
    title: "Under the hood",
    say: ["Plug-in checks: a new check is one class. The drawing defines what to expect, so a new cabinet needs no training.", "Honest limits: generated test cabinets copy Emerson's layout; real photos will be harder. Next: YOLO detector, PaddleOCR."],
    action: "Open the engine page", run: () => go("engine"),
  },
];

export function Presenter({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [n, setN] = useState(() => {
    try {
      return Math.min(STEPS.length - 1, Number(sessionStorage.getItem("ee_tour") ?? 0));
    } catch {
      return 0;
    }
  });
  const [min, setMin] = useState(false);
  useEffect(() => {
    try {
      sessionStorage.setItem("ee_tour", String(n));
    } catch {
      /* ignore */
    }
  }, [n]);

  const next = () => setN((x) => Math.min(STEPS.length - 1, x + 1));
  const prev = () => setN((x) => Math.max(0, x - 1));
  const run = (i = n) => void STEPS[i].run();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      if (e.key === "PageDown" || e.key === "]") { e.preventDefault(); const i = Math.min(STEPS.length - 1, n + 1); setN(i); run(i); }
      if (e.key === "PageUp" || e.key === "[") { e.preventDefault(); const i = Math.max(0, n - 1); setN(i); run(i); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, n]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = STEPS[n];
  return (
    <AnimatePresence>
      {open && (
        <motion.aside className={`presenter card${min ? " min" : ""}`} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 16 }} aria-label="Presenter mode">
          <div className="row between presenter-head">
            <button className="row tiny faint" style={{ ["--gap" as string]: "7px" }} onClick={() => setMin(!min)} title={min ? "Expand" : "Collapse"}>
              <Mic size={13} /> <span className="mono">PRESENTER · {n + 1}/{STEPS.length}</span>
            </button>
            <button className="btn btn-icon btn-sm btn-ghost" onClick={onClose} aria-label="Close presenter mode"><X /></button>
          </div>
          {!min && (
            <>
              <div className="presenter-bar"><i style={{ width: `${((n + 1) / STEPS.length) * 100}%` }} /></div>
              <AnimatePresence mode="wait">
                <motion.div key={n} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.18 }}>
                  <h3>{s.title}</h3>
                  <ul>{s.say.map((x) => <li key={x}>{x}</li>)}</ul>
                </motion.div>
              </AnimatePresence>
              <div className="row between" style={{ ["--gap" as string]: "6px" }}>
                <button className="btn btn-sm btn-icon" onClick={prev} disabled={n === 0} aria-label="Previous step"><ChevronLeft /></button>
                <button className="btn btn-sm btn-primary grow" onClick={() => run()}><Play /> {s.action}</button>
                <button className="btn btn-sm btn-icon" onClick={next} disabled={n === STEPS.length - 1} aria-label="Next step"><ChevronRight /></button>
              </div>
              <div className="tiny faint">Clicker: <kbd>PgDn</kbd> next step + do it · <kbd>PgUp</kbd> back</div>
            </>
          )}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
