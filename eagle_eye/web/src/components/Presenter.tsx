import { AnimatePresence, motion } from "framer-motion";
import { Observer } from "gsap/Observer";
import { ChevronLeft, ChevronRight, Maximize2, Mic, Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { go } from "../lib/router";
import { Lightning } from "./Lightning";

gsap.registerPlugin(Observer);

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
    say: ["The Python engine runs local OCR, drawing registration, checks and evidence validation without an external AI API.", "This demo uses a generated cabinet and its matching drawing. Real-photo processing time depends on detail and hardware."],
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
    say: ["Fault Forge builds a generated cabinet, plants hidden faults, and varies the camera and lighting.", "The recorded synthetic baseline caught 87 / 87 planted faults with 0 false alarms on 1,950 correct synthetic items. The comparison panel keeps real evaluation separate."],
    action: "Forge a cabinet", run: () => go("forge/run"),
  },
  {
    title: "Bad photos",
    say: ["Tilt, blur, glare, dim light, JPEG noise: the stress sweep makes a generated photo progressively worse.", "Measure confirmed detections, false alarms and review referrals; do not infer real-photo accuracy from this test."],
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

/** #40 presenter slide engine: the demo script as dark full-screen slides. Wheel, touch, arrows and the clicker's
 *  PgUp/PgDn move between slides (Observer); Enter or the button performs the step and returns to the console. */
function Slides({ start, onClose, onRun }: { start: number; onClose: () => void; onRun: (i: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [i, setI] = useState(start);
  const goRef = useRef<(n: number) => void>(() => {});
  useGSAP(() => {
    const root = ref.current!;
    const slides = gsap.utils.toArray<HTMLElement>(".slide", root);
    let cur = start;
    let busy = false;
    gsap.set(slides, { autoAlpha: 0 });
    gsap.set(slides[cur], { autoAlpha: 1 });
    if (!calm()) gsap.from(root, { autoAlpha: 0, duration: 0.35 });
    const go = (n: number) => {
      if (busy || n < 0 || n >= slides.length || n === cur) return;
      const dir = n > cur ? 1 : -1;
      busy = true;
      const d = calm() ? 0 : 1;
      gsap.timeline({ onComplete: () => void (busy = false) })
        .to(slides[cur], { yPercent: -8 * dir, opacity: 0, duration: 0.35 * d })
        .set(slides[cur], { visibility: "hidden", yPercent: 0 })
        .fromTo(slides[n], { yPercent: 8 * dir, autoAlpha: 0 }, { yPercent: 0, autoAlpha: 1, duration: 0.45 * d }, "<0.1")
        .from(slides[n].querySelectorAll(".slide-say li"), { y: 14, opacity: 0, stagger: 0.08, duration: 0.4 * d }, "<0.15");
      cur = n;
      setI(n);
    };
    goRef.current = go;
    Observer.create({ target: root, type: "wheel,touch", tolerance: 12, preventDefault: true, onDown: () => go(cur + 1), onUp: () => go(cur - 1) });
    const onKey = (e: KeyboardEvent) => {
      if (["ArrowDown", "ArrowRight", "PageDown", " ", "]"].includes(e.key)) { e.preventDefault(); go(cur + 1); }
      else if (["ArrowUp", "ArrowLeft", "PageUp", "["].includes(e.key)) { e.preventDefault(); go(cur - 1); }
      else if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "Enter") { e.preventDefault(); onRun(cur); }
    };
    window.addEventListener("keydown", onKey);
    const html = document.documentElement;
    const prev = html.style.overflow;
    html.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      html.style.overflow = prev;
    };
  }, { scope: ref });

  return createPortal(
    <div className="slides device" ref={ref} role="dialog" aria-label="Presenter slides">
      <Lightning hue={212} xOffset={-1.1} speed={0.45} intensity={0.36} size={1.4} />
      <div className="slides-mesh" aria-hidden="true"><i className="blob s1" /><i className="blob s2" /></div>
      <button className="btn btn-icon btn-ghost slides-close" onClick={onClose} aria-label="Close slides"><X /></button>
      {STEPS.map((st, n) => (
        <section key={st.title} className="slide" aria-hidden={n !== i}>
          <div className="slide-n mono">{String(n + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")}</div>
          <h2 className="slide-title">{st.title}</h2>
          <ul className="slide-say">{st.say.map((x) => <li key={x}>{x}</li>)}</ul>
          <button className="btn btn-primary btn-xl" onClick={() => onRun(n)} data-magnetic=""><i className="shine" aria-hidden="true" /><Play /> <span>{st.action}</span></button>
        </section>
      ))}
      <div className="slides-foot mono">
        <div className="slides-dots">{STEPS.map((st, n) => <button key={st.title} className={n === i ? "on" : ""} aria-label={`Slide ${n + 1}`} onClick={() => goRef.current(n)} />)}</div>
        <span>scroll · swipe · ← → · PgUp PgDn · Enter does the step · Esc</span>
      </div>
    </div>,
    document.body,
  );
}

export function Presenter({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [n, setN] = useState(() => {
    try {
      return Math.min(STEPS.length - 1, Number(sessionStorage.getItem("ee_tour") ?? 0));
    } catch {
      return 0;
    }
  });
  const [min, setMin] = useState(false);
  const [slides, setSlides] = useState(false);
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
    if (!open || slides) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      if (e.key === "PageDown" || e.key === "]") { e.preventDefault(); const i = Math.min(STEPS.length - 1, n + 1); setN(i); run(i); }
      if (e.key === "PageUp" || e.key === "[") { e.preventDefault(); const i = Math.max(0, n - 1); setN(i); run(i); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, n, slides]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = STEPS[n];
  return (
    <>
    {open && slides && <Slides start={n} onClose={() => setSlides(false)} onRun={(i) => { setN(i); setSlides(false); run(i); }} />}
    <AnimatePresence>
      {open && (
        <motion.aside className={`presenter card${min ? " min" : ""}`} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 16 }} aria-label="Presenter mode">
          <div className="row between presenter-head">
            <button className="row tiny faint" style={{ ["--gap" as string]: "7px" }} onClick={() => setMin(!min)} title={min ? "Expand" : "Collapse"}>
              <Mic size={13} /> <span className="mono">PRESENTER · {n + 1}/{STEPS.length}</span>
            </button>
            <div className="row" style={{ ["--gap" as string]: "4px" }}>
              <button className="btn btn-icon btn-sm btn-ghost" onClick={() => setSlides(true)} aria-label="Full-screen slides" title="Full-screen slides"><Maximize2 /></button>
              <button className="btn btn-icon btn-sm btn-ghost" onClick={onClose} aria-label="Close presenter mode"><X /></button>
            </div>
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
    </>
  );
}
