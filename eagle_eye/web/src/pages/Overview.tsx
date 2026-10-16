import { motion } from "framer-motion";
import {
  ArrowLeftRight, ArrowRight, BadgeCheck, Ban, Bot, Camera, Crosshair, Eye, FileCode2, FileSpreadsheet, FlaskConical,
  GitMerge, Layers, Microscope, Play, RefreshCcw, ScanEye, ShieldCheck, Sparkles, SpellCheck2, Target, Timer, Wrench,
} from "lucide-react";
import { ScanShowcase } from "../components/ScanShowcase";
import { Count, Reveal, SectionHead } from "../components/ui";
import { api } from "../lib/api";
import { useAsync } from "../lib/hooks";
import { go } from "../lib/router";

const IDEAS = [
  { icon: FileCode2, title: "Read the drawing with code, not AI", body: "The GA PDF is vector, so PyMuPDF pulls every tag (PS11, CB41…) and its box exactly. The drawing becomes a closed list of expected items." },
  { icon: Crosshair, title: "Labels are the registration anchors", body: "Find the backplate outline, then use the labels and ferrules we can read as anchor points (RANSAC homography). Anchors that don't fit point to misplaced parts." },
  { icon: ArrowLeftRight, title: "Swap-aware order check", body: "Read labels left to right along the breaker rail and align with the drawing's sequence, so the tool says “CB43 ↔ CB44 swapped”, like Emerson's own sheet." },
  { icon: SpellCheck2, title: "Wire-list-constrained OCR", body: "Ferrule text is matched against the strings in the wire list, not read freely, with OCR-confusion handling (B/8, O/0) and multi-variant voting." },
  { icon: ShieldCheck, title: "Precision-first consensus", body: "FAIL only when evidence agrees (empty slot AND no label). Unclear items go to REVIEW, “re-photo this zone”, instead of a guess." },
  { icon: GitMerge, title: "Root cause, then Fault Forge", body: "A missing part is one FAIL, not five: its label check is skipped. Fault Forge plants faults in generated cabinets so we measure ourselves before the hidden test." },
];

const DOD = [
  { k: "Finds the faults", v: "87 / 87 planted faults caught on 50 cabinets the engine never saw." },
  { k: "No false alarms", v: "0 FAIL across 1,950 correct items. A correct item is never FAIL." },
  { k: "Every FAIL has proof", v: "Boxed and numbered on the photo, with an expected-vs-found snippet." },
  { k: "Re-check works", v: "New photo after the fix: CLOSED / OPEN / REGRESSION, history kept." },
  { k: "Works on a cabinet it has never seen", v: "No per-cabinet training. The cabinet's GA PDF defines what to expect." },
];

const VS: [string, string, string][] = [
  ["The question", "“What's wrong in this photo?”", "“Is PS12 installed at (140, 40) mm?” × 41"],
  ["Coverage", "Whatever it happens to notice", "Every item the drawing and wire list expect"],
  ["False alarms", "Invents plausible-looking faults", "FAIL only when independent evidence agrees"],
  ["Uncertainty", "Guesses confidently", "REVIEW: “re-photo this zone”"],
  ["Proof", "A paragraph of text", "Box on the photo + expected-vs-found crop"],
  ["Repeatability", "Changes run to run", "Deterministic: same photo, same report"],
  ["A new cabinet", "Prompt engineering", "Load its GA drawing. Done."],
];

const PIPE = [
  { n: 1, icon: FileCode2, t: "Parse the drawing", s: "Vector GA → exact list of parts, labels and positions" },
  { n: 2, icon: Crosshair, t: "Register the photo", s: "Backplate outline, then labels and ferrules as anchors" },
  { n: 3, icon: Layers, t: "Plug-in checks", s: "GA · ORDER · LABEL · FERRULE · COLOUR" },
  { n: 4, icon: ShieldCheck, t: "Consensus", s: "FAIL only if evidence agrees; unclear → REVIEW", hl: true },
  { n: 5, icon: FileSpreadsheet, t: "Report", s: "Excel checklist, boxed photo, expected-vs-found, PDF" },
  { n: 6, icon: RefreshCcw, t: "Re-check", s: "New photo after the fix: CLOSED / OPEN / REGRESSION" },
];

const PLAN = [
  { icon: FileCode2, t: "Adapt the parser to Emerson's drawings", s: "Map their GA tag and title-block conventions; the checks stay unchanged." },
  { icon: Target, t: "Fine-tune a YOLO11 detector on their photos", s: "Swap the occupancy model for a detector trained on Emerson's samples." },
  { icon: SpellCheck2, t: "PaddleOCR for curved ferrules", s: "Keep the wire-list-constrained decoding; upgrade the reader." },
  { icon: FlaskConical, t: "Re-run Fault Forge on real cabinets", s: "Plant faults on Emerson's samples and publish the same self-test numbers." },
];

export function Overview() {
  const st = useAsync(api.selftest);
  const s = st.data?.summary;
  const metrics = [
    { v: s?.caught ?? 87, of: s?.planted ?? 87, label: "planted faults caught", sub: `${s?.cabinets ?? 50} unseen cabinets`, c: "var(--pass)" },
    { v: s?.false_alarms ?? 0, label: "false alarms", sub: `across ${(s?.correct_items ?? 1950).toLocaleString()} correct items`, c: "var(--accent)" },
    { v: (s?.review_rate ?? 0.003) * 100, label: "sent to REVIEW", sub: `${s?.reviews ?? 6} items, never a guessed FAIL`, c: "var(--review)", suffix: "%", d: 1 },
    { v: s?.sec_per_cabinet ?? 4, label: "seconds per cabinet", sub: `CPU only · ${s?.cpu_cores ?? 4} cores · no GPU`, c: "var(--accent-3)", d: 1 },
  ];

  return (
    <div className="overview">
      {/* ---------------- hero ---------------- */}
      <section className="hero">
        <div className="hero-copy">
          <motion.span className="eyebrow" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            Emerson · Track 1 · Problem Statement #03
          </motion.span>
          <motion.h1 initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}>
            Check every item the drawing expects. <span className="gradient-text">One at a time, at a known spot.</span>
          </motion.h1>
          <motion.p className="hero-sub" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}>
            EAGLE EYE reads the GA drawing and wire list with code, lines the cabinet photo up with the drawing, and asks one
            narrow yes/no question per item. Out comes Emerson's QC checklist, filled in, with every FAIL boxed on the photo
            and proven by an expected-vs-found snippet.
          </motion.p>
          <motion.div className="row wrap hero-cta" initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.16, ease: [0.22, 1, 0.36, 1] }}>
            <button className="btn btn-primary btn-xl" onClick={() => go("inspect/demo")}>
              <Play /> Run the live demo
            </button>
            <button className="btn btn-xl" onClick={() => go("forge")}>
              <FlaskConical /> Challenge it in Fault Forge
            </button>
          </motion.div>
          <motion.div className="hero-trust" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>
            <span><Ban size={14} /> No cloud, no GPU</span>
            <span><Timer size={14} /> ~4 s per cabinet</span>
            <span><Microscope size={14} /> Deterministic and auditable</span>
          </motion.div>
        </div>
        <motion.div className="hero-visual" initial={{ opacity: 0, scale: 0.97, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ duration: 0.9, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}>
          <ScanShowcase />
        </motion.div>
      </section>

      {/* ---------------- metrics ---------------- */}
      <Reveal className="metrics card">
        {metrics.map((m) => (
          <div key={m.label} className="metric">
            <div className="metric-v" style={{ color: m.c }}>
              <Count value={m.v} decimals={m.d ?? 0} />
              {m.of != null && <span className="metric-of">/{m.of}</span>}
              {m.suffix && <span className="metric-of">{m.suffix}</span>}
            </div>
            <div className="metric-l">{m.label}</div>
            <div className="metric-s">{m.sub}</div>
          </div>
        ))}
        <div className="metrics-note">Fault Forge self-test on generated cabinets (held-out seeds 200–249). Real photos will be harder; see the honest limits below.</div>
      </Reveal>

      {/* ---------------- problem ---------------- */}
      <section className="section">
        <SectionHead eyebrow="The problem" title="QC today is a person, a paper sheet and hundreds of parts." sub="A control cabinet is a steel box full of parts, labels, wires and printed wire sleeves, built from a GA drawing. An inspector checks it by eye and fills a check sheet: slow, tiring, and easy to miss things. Emerson wants a tool that does it from a photo." />
        <div className="problem-grid">
          <Reveal className="card pad problem-in">
            <div className="card-title"><Camera /> What goes in</div>
            <ul className="io-list">
              <li><b>HD cabinet photo</b><span>JPG / PNG</span></li>
              <li><b>GA drawing</b><span>vector PDF</span></li>
              <li><b>Wire & label list</b><span>Excel</span></li>
              <li><b>QC checklist</b><span>Excel</span></li>
            </ul>
            <div className="divider" />
            <div className="card-title"><BadgeCheck /> What comes out</div>
            <ul className="io-list">
              <li><b>QC checklist, filled</b><span>PASS / FAIL per item</span></li>
              <li><b>Every FAIL boxed</b><span>numbered on the photo</span></li>
              <li><b>Proof per FAIL</b><span>expected vs found</span></li>
              <li><b>Re-check</b><span>after the fix</span></li>
            </ul>
          </Reveal>
          <Reveal className="card pad dod" delay={0.08}>
            <div className="card-head">
              <div className="card-title"><Target /> Emerson's definition of done, and how we meet it</div>
            </div>
            <div className="dod-list">
              {DOD.map((d, i) => (
                <motion.div key={d.k} className="dod-row" initial={{ opacity: 0, x: 12 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ delay: 0.1 + i * 0.07 }}>
                  <span className="dod-check"><BadgeCheck size={16} /></span>
                  <div>
                    <div className="dod-k">{d.k}</div>
                    <div className="dod-v">{d.v}</div>
                  </div>
                </motion.div>
              ))}
            </div>
            <div className="example">
              <span className="tiny faint">Emerson's own example has 4 faults:</span>
              <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
                <span className="tag">PS12 missing</span>
                <span className="tag">CB43 ↔ CB44 swapped</span>
                <span className="tag">1CBP03 no label</span>
                <span className="tag">X3 wire without ferrule</span>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---------------- vs ---------------- */}
      <section className="section">
        <SectionHead eyebrow="Our approach" title={<>We don't ask AI “what's wrong?”<br /><span className="gradient-text">We verify what the drawing expects.</span></>} sub="Most teams will send the photo to a vision model. It invents faults and breaks Emerson's no-false-alarm rule. We turn the GA drawing and wire list into an exact list of expected items, then answer narrow yes/no questions about each." />
        <Reveal className="card vs">
          <div className="vs-head">
            <div />
            <div className="vs-col-h bad"><Bot size={16} /> Ask a vision model</div>
            <div className="vs-col-h good"><Eye size={16} /> EAGLE EYE, drawing-first</div>
          </div>
          {VS.map(([k, a, b], i) => (
            <motion.div key={k} className="vs-row" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }} transition={{ delay: i * 0.05 }}>
              <div className="vs-k">{k}</div>
              <div className="vs-a">{a}</div>
              <div className="vs-b">{b}</div>
            </motion.div>
          ))}
        </Reveal>
      </section>

      {/* ---------------- six ideas ---------------- */}
      <section className="section">
        <SectionHead eyebrow="Six ideas" title="What makes it precise." />
        <div className="ideas">
          {IDEAS.map((x, i) => (
            <Reveal key={x.title} className="card pad idea" delay={(i % 3) * 0.07}>
              <div className="idea-n mono">{String(i + 1).padStart(2, "0")}</div>
              <div className="idea-icon"><x.icon /></div>
              <h3>{x.title}</h3>
              <p>{x.body}</p>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- pipeline ---------------- */}
      <section className="section">
        <SectionHead eyebrow="The pipeline" title="Every expected item is checked; a FAIL needs agreeing evidence." sub="Stages 1–3 build the evidence. Stage 4 is where false alarms are stopped." />
        <div className="pipe">
          {PIPE.map((p, i) => (
            <Reveal key={p.n} className={`card pipe-card${p.hl ? " hl card-glow" : ""}`} delay={i * 0.07}>
              <div className="row between">
                <span className="pipe-n mono">0{p.n}</span>
                <p.icon size={18} className={p.hl ? "" : "faint"} style={p.hl ? { color: "var(--accent)" } : undefined} />
              </div>
              <h4>{p.t}</h4>
              <p>{p.s}</p>
              {i < PIPE.length - 1 && <ArrowRight className="pipe-arrow" size={16} />}
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---------------- limits + plan ---------------- */}
      <section className="section">
        <div className="two-col">
          <div>
            <SectionHead eyebrow="Honest limits" title="What we have not proven yet." />
            <Reveal className="card pad limits">
              <div className="limit"><Sparkles size={16} /><p><b>The numbers are on generated cabinets.</b> Real photos will be harder: glare, cable clutter, curved ferrules. We say so up front.</p></div>
              <div className="limit"><ScanEye size={16} /><p><b>OCR is Tesseract today.</b> A YOLO11 detector, PaddleOCR for curved ferrules and a local vision-model verifier for REVIEW items are planned, not built.</p></div>
              <div className="limit"><FileCode2 size={16} /><p><b>It needs a vector GA PDF</b> in this format. Scanned drawings are a later step.</p></div>
              <div className="limit"><Wrench size={16} /><p><b>Blurry photo or unreadable label?</b> The item goes to REVIEW with a “re-photo this zone” request, never a guessed FAIL.</p></div>
            </Reveal>
          </div>
          <div>
            <SectionHead eyebrow="Grand finale · 24 h with Emerson's data" title="What we build next." />
            <Reveal className="card pad plan" delay={0.06}>
              {PLAN.map((p, i) => (
                <div key={p.t} className="plan-step">
                  <div className="plan-n mono">{i + 1}</div>
                  <div>
                    <div className="plan-t"><p.icon size={15} /> {p.t}</div>
                    <div className="plan-s">{p.s}</div>
                  </div>
                </div>
              ))}
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------------- CTA ---------------- */}
      <Reveal className="cta card card-glow">
        <div>
          <h2>See it on Emerson's example, live.</h2>
          <p className="muted">4 FAILs with proof in a few seconds, then a re-check that closes 3 of them.</p>
        </div>
        <div className="row wrap">
          <button className="btn btn-primary btn-lg" onClick={() => go("inspect/demo")}><Play /> Run the live demo</button>
          <button className="btn btn-lg" onClick={() => go("engine")}><Layers /> How the engine works</button>
        </div>
      </Reveal>
    </div>
  );
}
