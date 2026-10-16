import { AnimatePresence, motion } from "framer-motion";
import { RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { url } from "../lib/api";
import { STATUS_HEX } from "../lib/format";
import showcase from "../data/showcase.json";
import type { Pt } from "../lib/types";

type Phase = 0 | 1 | 2 | 3 | 4;
const STEPS: { at: number; phase: Phase; hud: string }[] = [
  { at: 0, phase: 0, hud: "Acquiring backplate" },
  { at: 1300, phase: 1, hud: "Drawing laid onto the photo · 20 expected items" },
  { at: 2900, phase: 2, hud: `${showcase.anchors.length} label & ferrule anchors locked` },
  { at: 4300, phase: 3, hud: "Checking 41 items, one at a time" },
  { at: 5600, phase: 4, hud: "4 FAIL with proof · 0 false alarms" },
];

const pts = (q: number[][]) => q.map((p) => p.join(",")).join(" ");
const bb = (q: number[][]) => {
  const xs = q.map((p) => p[0]);
  const ys = q.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
};

/** Hero visual: replays a real inspection of Emerson's example cabinet, stage by stage. */
export function ScanShowcase() {
  const [phase, setPhase] = useState<Phase>(0);
  const [hud, setHud] = useState(STEPS[0].hud);
  const [run, setRun] = useState(0);
  const [W, H] = showcase.photo_size as [number, number];

  useEffect(() => {
    const ts = STEPS.map((s) => setTimeout(() => { setPhase(s.phase); setHud(s.hud); }, s.at));
    const loop = setTimeout(() => setRun((r) => r + 1), 15000);
    return () => { ts.forEach(clearTimeout); clearTimeout(loop); };
  }, [run]);

  return (
    <div className="showcase card card-glow">
      <div className="showcase-frame" style={{ aspectRatio: `${W} / ${H}` }}>
        <img src={url.sample("01", 1100)} alt="Control cabinet photo: Emerson's example with four planted faults" />
        <svg viewBox={`0 0 ${W} ${H}`}>
          <polygon points={pts(showcase.backplate)} className={`sc-bp${phase >= 1 ? " on" : ""}`} />
          <g className={`sc-layout${phase >= 1 ? " on" : ""}`}>
            {showcase.layout.map((l, i) => (
              <polygon key={l.tag} points={pts(l.quad)} style={{ transitionDelay: `${i * 45}ms` }} />
            ))}
          </g>
          <g className={`sc-anchors${phase >= 2 ? " on" : ""}`}>
            {showcase.anchors.map((a, i) => (
              <circle key={a.tag + i} cx={(a.p as Pt)[0]} cy={(a.p as Pt)[1]} r={13} className={a.inlier === false ? "out" : ""} style={{ transitionDelay: `${i * 40}ms` }} />
            ))}
          </g>
          {phase >= 4 &&
            showcase.issues.map((it, i) => {
              const b = bb(it.quad);
              const c = STATUS_HEX[it.result as "FAIL"];
              return (
                <motion.g key={it.id + run} initial={{ opacity: 0, scale: 1.25 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.22, type: "spring", stiffness: 260, damping: 18 }} style={{ transformOrigin: `${(b.x0 + b.x1) / 2}px ${(b.y0 + b.y1) / 2}px` }}>
                  <rect x={b.x0 - 14} y={b.y0 - 14} width={b.x1 - b.x0 + 28} height={b.y1 - b.y0 + 28} rx={12} fill={c} fillOpacity={0.18} stroke={c} strokeWidth={13} />
                  <circle cx={b.x1 + 14} cy={b.y0 - 14} r={50} fill={c} stroke="#fff" strokeWidth={8} />
                  <text x={b.x1 + 14} y={b.y0 + 6} textAnchor="middle" className="sc-num">{it.marker}</text>
                </motion.g>
              );
            })}
        </svg>
        {phase < 4 && <div className="scan"><div className="scan-beam" /></div>}
        <div className="showcase-hud">
          <span className={`dot${phase < 4 ? " pulse" : ""}`} style={{ ["--c" as string]: phase < 4 ? "var(--accent)" : "var(--fail)" }} />
          <AnimatePresence mode="wait">
            <motion.span key={hud} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }}>
              {hud}
            </motion.span>
          </AnimatePresence>
        </div>
        <button className="btn btn-sm btn-icon showcase-replay" onClick={() => { setPhase(0); setHud(STEPS[0].hud); setRun((r) => r + 1); }} aria-label="Replay">
          <RotateCcw />
        </button>
      </div>
      <AnimatePresence>
        {phase >= 4 && (
          <motion.div className="showcase-list" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ delay: 0.9 }}>
            {showcase.issues.map((it) => (
              <div key={it.id} className="showcase-item">
                <span className="marker" style={{ ["--c" as string]: "var(--fail)", width: 20, height: 20, fontSize: 10.5 }}>{it.marker}</span>
                <span className="mono">{it.id}</span>
                <span className="faint ellipsis">{it.found}</span>
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
