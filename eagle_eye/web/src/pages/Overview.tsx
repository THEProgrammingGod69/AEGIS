import {
  Aperture, ArrowLeftRight, ArrowRight, BadgeCheck, BarChart3, Camera, ClipboardList, Cloud, Command, Crosshair, FileCode2,
  FileSpreadsheet, FlaskConical, Gauge, GitMerge, Layers, Microscope, Play, RefreshCcw, ScanEye, ShieldCheck, Sparkles, SpellCheck2,
  Target, UserCheck, Wrench,
} from "lucide-react";
import { useRef } from "react";
import { Cursor } from "../components/Cursor";
import { Lightning } from "../components/Lightning";
import { Marquee, Odometer, Scramble } from "../components/motion";
import { Hero } from "../components/overview/Hero";
import { Exploded, PipelineScroll, ValuesDeck, VsTable } from "../components/overview/Story";
import { XrayLens } from "../components/overview/XrayLens";
import { Count, Reveal, SectionHead } from "../components/ui";
import { api } from "../lib/api";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { useAsync } from "../lib/hooks";
import { go } from "../lib/router";
import { useSmoothScroll } from "../lib/smooth";
import { blinkTo } from "../lib/transition";
import { tone } from "../lib/format";

const IDEAS = [
  { icon: FileCode2, title: "Read the drawing with code, not AI", body: "The GA PDF is vector, so PyMuPDF pulls every tag (PS11, CB41…) and its box exactly. The drawing becomes a closed list of expected items." },
  { icon: Crosshair, title: "Labels are the registration anchors", body: "Find the backplate outline, then use the labels and ferrules we can read as anchor points (RANSAC homography). Anchors that don't fit point to misplaced parts." },
  { icon: ArrowLeftRight, title: "Swap-aware order check", body: "Read labels left to right along the breaker rail and align with the drawing's sequence, so the tool says “CB43 ↔ CB44 swapped”, like Emerson's own sheet." },
  { icon: SpellCheck2, title: "Wire-list-constrained OCR", body: "Ferrule text is matched against the strings in the wire list, not read freely, with OCR-confusion handling (B/8, O/0) and multi-variant voting." },
  { icon: ShieldCheck, title: "Precision-first consensus", body: "FAIL only when evidence agrees (empty slot AND no label). Unclear items go to REVIEW, “re-photo this zone”, instead of a guess." },
  { icon: GitMerge, title: "Root cause, then Fault Forge", body: "A missing part is one FAIL, not five: its label check is skipped. Fault Forge plants faults in generated cabinets so we measure ourselves before the hidden test." },
];

const DOD = [
  { k: "Recorded synthetic baseline", v: "87 / 87 planted faults caught on 50 generated cabinet images in the recorded self-test." },
  { k: "Measured false alarms", v: "0 FAIL across 1,950 correct synthetic items in that test; real-world performance requires separate evaluation." },
  { k: "Every FAIL has proof", v: "Boxed and numbered on the photo, with an expected-vs-found snippet." },
  { k: "Re-check works", v: "New photo after the fix: CLOSED / OPEN / REGRESSION, history kept." },
  { k: "Drawing-driven inspection", v: "The matching GA PDF defines expectations. Supported drawings, readable labels and reliable alignment are required." },
];

const VS: [string, string, string][] = [
  ["The question", "“What's wrong in this photo?”", "“Is PS12 installed at (140, 40) mm?” × 41"],
  ["Coverage", "Whatever it happens to notice", "Every item the drawing and wire list expect"],
  ["False alarms", "Invents plausible-looking faults", "FAIL only when independent evidence agrees"],
  ["Uncertainty", "Guesses confidently", "REVIEW: “re-photo this zone”"],
  ["Proof", "A paragraph of text", "Box on the photo + expected-vs-found crop"],
  ["Repeatability", "Changes run to run", "Deterministic: same photo, same report"],
  ["A new cabinet", "Prompt engineering", "Validate its drawing, label visibility and alignment"],
];

const PIPE = [
  { n: 1, icon: FileCode2, t: "Parse the drawing", s: "Vector GA → exact list of parts, labels and positions" },
  { n: 2, icon: Crosshair, t: "Register the photo", s: "Backplate outline, then labels and ferrules as anchors" },
  { n: 3, icon: Layers, t: "Plug-in checks", s: "GA · ORDER · LABEL · FERRULE · COLOUR" },
  { n: 4, icon: ShieldCheck, t: "Consensus", s: "FAIL only if evidence agrees; unclear → REVIEW", hl: true },
  { n: 5, icon: FileSpreadsheet, t: "Report", s: "Excel checklist, boxed photo, expected-vs-found, PDF" },
  { n: 6, icon: RefreshCcw, t: "Re-check", s: "New photo after the fix: CLOSED / OPEN / REGRESSION" },
];

const NEW = [
  { icon: Cloud, t: "Local vision inspection", s: "Your configured backend runs OCR and geometry without an external AI API. Real photographs require the matching drawing; unresolved checks block approval.", to: "inspect", tag: "drawing required" },
  { icon: Gauge, t: "5× faster engine", s: "OCR now runs in-process through libtesseract: identical text on 1,668 crops, identical self-test, 4 s → 0.9 s per cabinet.", to: "engine", tag: "same results" },
  { icon: ClipboardList, t: "Technician work orders", s: "Every FAIL becomes a numbered fix with location, proof crops, time estimate and sign-off. Print or save as PDF.", to: "history", tag: "printable" },
  { icon: UserCheck, t: "Review station", s: "Human in the loop: inspectors confirm or overturn findings with the proof on screen. Every decision is audit-logged.", to: "review", tag: "audit trail" },
  { icon: BarChart3, t: "QC analytics", s: "First-pass yield, fix closure, inspector agreement, time saved, and a heatmap of where faults cluster on the cabinet.", to: "analytics", tag: "heatmap" },
  { icon: Microscope, t: "Robustness Lab", s: "Tilt, blur, glare, noise, colour cast: degrade a photo and watch findings move to REVIEW instead of false FAILs.", to: "lab", tag: "stress sweep" },
  { icon: Aperture, t: "Capture assistant", s: "Camera capture with a framing guide, plus an instant photo score (sharpness, exposure, glare) before a run is wasted.", to: "inspect", tag: "on device" },
  { icon: Command, t: "Presenter mode + ⌘K", s: "A command palette to jump anywhere and a step-by-step demo script with clicker support.", to: "", tag: "Ctrl K" },
];

const PLAN = [
  { icon: FileCode2, t: "Adapt the parser to Emerson's drawings", s: "Map their GA tag and title-block conventions; the checks stay unchanged." },
  { icon: Target, t: "Fine-tune a YOLO11 detector on their photos", s: "Swap the occupancy model for a detector trained on Emerson's samples." },
  { icon: SpellCheck2, t: "PaddleOCR for curved ferrules", s: "Keep the wire-list-constrained decoding; upgrade the reader." },
  { icon: FlaskConical, t: "Evaluate real cabinets separately", s: "Use verified real defects and independent cabinets; report confirmed detections, review referrals and incorrect approvals separately." },
];

const BAND = [
  "87 / 87 planted faults caught", "0 false alarms on 1,950 items", "41 checks per cabinet", "Deterministic", "No training per cabinet",
  "CB43 ↔ CB44 swapped", "PS12 missing", "X3:3 no ferrule", "REVIEW, never a guess", "CPU only · no GPU", "Proof for every FAIL",
];

const NAV_LABEL: Record<string, string> = { inspect: "Inspect", engine: "Engine", history: "History", review: "Review", analytics: "Analytics", lab: "Robustness", "": "Overview" };

export function Overview({ onPresent }: { onPresent?: () => void }) {
  const st = useAsync(api.selftest);
  const s = st.data?.summary;
  const root = useRef<HTMLDivElement>(null);
  useSmoothScroll();

  // #14 parallax depth layers: [data-speed] drifts against the scroll
  useGSAP(() => {
    if (calm()) return;
    gsap.utils.toArray<HTMLElement>("[data-speed]").forEach((el) =>
      gsap.to(el, { yPercent: () => -20 * Number(el.dataset.speed), ease: "none", scrollTrigger: { trigger: el.parentElement, start: "top bottom", end: "bottom top", scrub: true } }),
    );
  }, { scope: root });

  const metrics = [
    { v: s?.false_alarms ?? 0, label: "synthetic false alarms", sub: `across ${(s?.correct_items ?? 1950).toLocaleString()} correct synthetic items`, c: "var(--pass)" },
    { v: (s?.review_rate ?? 0.003) * 100, label: "sent to REVIEW", sub: `${s?.reviews ?? 6} items, never a guessed FAIL`, c: "var(--review)", suffix: "%", d: 1 },
  ];

  return (
    <div className="overview" ref={root}>
      <Cursor />
      <Hero s={s} onPresent={onPresent} />

      <div className="band-wrap">
        <Marquee className="band">
          {BAND.map((b) => (
            <span key={b} className="band-item mono">{b}<i aria-hidden="true">◆</i></span>
          ))}
        </Marquee>
      </div>

      <div className="main ov-main">
        {/* ---------------- stats band ---------------- */}
        <Reveal className="stats-band card aurora-border" data-spotlight="">
          <div className="stat stat-hero">
            <div className="stat-v"><Odometer value={s?.caught ?? 87} className="odo-aurora" /><span className="stat-of">/{s?.planted ?? 87}</span></div>
            <div className="stat-l">synthetic faults caught</div>
            <div className="stat-s">{s?.cabinets ?? 50} generated cabinet images · recorded baseline</div>
          </div>
          {metrics.map((m) => (
            <div key={m.label} className="stat">
              <div className="stat-v" style={{ color: m.c }}>
                <Count value={m.v} decimals={m.d ?? 0} />
                {m.suffix && <span className="stat-of">{m.suffix}</span>}
              </div>
              <div className="stat-l">{m.label}</div>
              <div className="stat-s">{m.sub}</div>
            </div>
          ))}
          <div className="stat">
            <div className="stat-v brand-ink"><Scramble text={`${(s?.sec_per_cabinet ?? 0.9).toFixed(1)} s`} chars="0123456789." className="metric-time" /></div>
            <div className="stat-l">per synthetic image</div>
            <div className="stat-s">Recorded baseline · {s?.cpu_cores ?? 4} CPU cores</div>
          </div>
          <div className="stats-note">Fault Forge self-test on generated cabinets (held-out seeds 200–249). Real photos will be harder; see the honest limits below.</div>
        </Reveal>
      </div>

      {/* ---------------- story: exploded inspection (pinned) ---------------- */}
      <Exploded />

      <div className="main ov-main">
        {/* ---------------- round 3 ---------------- */}
        <section className="section">
          <SectionHead eyebrow="Round 3 · the complete prototype" title={<>From one photo to a closed work order. <span className="brand-ink">End to end, live.</span></>} sub="Inspect, prove, fix, re-check, review, learn. Every step below runs on the real engine, from this page." />
          <div className="new-grid">
            {NEW.map((x, i) => (
              <Reveal key={x.t} delay={(i % 4) * 0.06}>
                <button className="card pad new-card" data-spotlight="" data-tilt="7" data-cursor="Open" onClick={() => (x.to in NAV_LABEL ? blinkTo(`#/${x.to}`, NAV_LABEL[x.to]) : go(x.to))}>
                  <div className="row between">
                    <span className="new-icon"><x.icon /></span>
                    <span className="tag">{x.tag}</span>
                  </div>
                  <h3>{x.t}</h3>
                  <p>{x.s}</p>
                  <span className="new-go">Open <ArrowRight size={14} /></span>
                </button>
              </Reveal>
            ))}
          </div>
          <Reveal className="card pad flow">
            {["Photo", "Inspect", "Proof", "Work order", "Fix", "Re-check", "Review", "Analytics"].map((t, i, a) => (
              <div key={t} className="flow-step">
                <span className="flow-n mono">{String(i + 1).padStart(2, "0")}</span>
                <span>{t}</span>
                {i < a.length - 1 && <ArrowRight size={14} className="faint" />}
              </div>
            ))}
          </Reveal>
        </section>

        {/* ---------------- problem ---------------- */}
        <section className="section">
          <SectionHead eyebrow="The problem" title="QC today is a person, a paper sheet and hundreds of parts." sub="A control cabinet is a steel box full of parts, labels, wires and printed wire sleeves, built from a GA drawing. An inspector checks it by eye and fills a check sheet: slow, tiring, and easy to miss things. Emerson wants a tool that does it from a photo." />
          <div className="problem-grid">
            <Reveal className="card pad problem-in" data-spotlight="">
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
            <Reveal className="card pad dod" delay={0.08} data-spotlight="">
              <div className="card-head">
                <div className="card-title"><Target /> Emerson's definition of done, and how we meet it</div>
              </div>
              <div className="dod-list">
                {DOD.map((d) => (
                  <div key={d.k} className="dod-row">
                    <span className="dod-check"><BadgeCheck size={16} /></span>
                    <div>
                      <div className="dod-k">{d.k}</div>
                      <div className="dod-v">{d.v}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="example">
                <span className="tiny faint">Emerson's own example has 4 faults:</span>
                <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
                  <span className="badge" style={tone("var(--fail)")}>PS12 missing</span>
                  <span className="badge" style={tone("var(--fail)")}>CB43 ↔ CB44 swapped</span>
                  <span className="badge" style={tone("var(--fail)")}>1CBP03 no label</span>
                  <span className="badge" style={tone("var(--fail)")}>X3 wire without ferrule</span>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ---------------- vs (#18) ---------------- */}
        <section className="section">
          <SectionHead eyebrow="Our approach" title={<>We don't ask AI “what's wrong?”<br /><span className="brand-ink">We verify what the drawing expects.</span></>} sub="Most teams will send the photo to a vision model. It invents faults and breaks Emerson's no-false-alarm rule. We turn the GA drawing and wire list into an exact list of expected items, then answer narrow yes/no questions about each." />
          <VsTable rows={VS} />
        </section>

        {/* ---------------- six ideas: values deck (#19) ---------------- */}
        <section className="section">
          <SectionHead eyebrow="Six ideas" title="What makes it precise." sub="Dealt from the deck as you scroll: the six decisions that keep every FAIL honest." />
          <ValuesDeck items={IDEAS} />
        </section>
      </div>

      {/* ---------------- pipeline (#13, pinned horizontal) ---------------- */}
      <PipelineScroll steps={PIPE} />

      <div className="main ov-main">
        {/* ---------------- X-ray lens (#5) ---------------- */}
        <section className="section xray-section">
          <div className="xray-copy">
            <SectionHead eyebrow="X-ray lens" title={<>Drag to see the drawing <span className="brand-ink">under the photo.</span></>} sub="The lens shows the GA drawing exactly where the engine registered it on Emerson's example. Near a part it snaps and reads the verdict: PS12 is drawn but missing, CB43 and CB44 sit in each other's slots." />
            <Reveal className="xray-legend">
              <span><i className="lg-pass" /> drawing item verified</span>
              <span><i className="lg-fail" /> drawing item with a FAIL</span>
              <span className="tiny faint">Tip: press <kbd>X</kbd> anywhere for X-ray mode on every photo.</span>
            </Reveal>
          </div>
          <Reveal><XrayLens /></Reveal>
        </section>

        {/* ---------------- limits + plan ---------------- */}
        <section className="section">
          <div className="two-col">
            <div>
              <SectionHead eyebrow="Honest limits" title="What we have not proven yet." />
              <Reveal className="card pad limits" data-spotlight="">
                <div className="limit"><Sparkles size={16} /><p><b>The numbers are on generated cabinets.</b> Real photos will be harder: glare, cable clutter, curved ferrules. We say so up front.</p></div>
                <div className="limit"><ScanEye size={16} /><p><b>OCR is Tesseract today.</b> A YOLO11 detector, PaddleOCR for curved ferrules and a local vision-model verifier for REVIEW items are planned, not built.</p></div>
                <div className="limit"><FileCode2 size={16} /><p><b>It needs a vector GA PDF</b> in this format. Scanned drawings are a later step.</p></div>
                <div className="limit"><Wrench size={16} /><p><b>Blurry photo or unreadable label?</b> The item goes to REVIEW with a “re-photo this zone” request, never a guessed FAIL.</p></div>
              </Reveal>
            </div>
            <div>
              <SectionHead eyebrow="Grand finale · 24 h with Emerson's data" title="What we build next." />
              <Reveal className="card pad plan" delay={0.06} data-spotlight="">
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
      </div>

      {/* ---------------- dark CTA band with lightning ---------------- */}
      <section className="cta-band device">
        <Lightning hue={208} xOffset={-0.75} speed={0.55} intensity={0.75} size={1.5} />
        <div className="cta-mesh" aria-hidden="true"><i className="blob c1" data-speed="0.6" /><i className="blob c2" data-speed="-0.4" /></div>
        <div className="cta-glyphs" aria-hidden="true">
          <svg className="glyph g1" data-speed="1.2" viewBox="0 0 60 60"><circle cx="30" cy="30" r="18" /><path d="M30 4v14M30 42v14M4 30h14M42 30h14" /></svg>
          <svg className="glyph g2" data-speed="-0.8" viewBox="0 0 80 50"><rect x="2" y="2" width="76" height="46" rx="6" /></svg>
          <svg className="glyph g3" data-speed="0.9" viewBox="0 0 60 60"><circle cx="30" cy="30" r="10" /><circle cx="30" cy="30" r="22" /></svg>
        </div>
        <div className="cta-inner">
          <div>
            <span className="eyebrow">Live demo</span>
            <h2>See it on Emerson's example, <span className="aurora-text">live.</span></h2>
            <p>A synthetic example with four known faults, followed by a re-check after three are fixed. Real-photo timing and accuracy are evaluated separately.</p>
          </div>
          <div className="row wrap cta-actions">
            <button className="btn btn-primary btn-xl" data-magnetic="" data-cursor="Inspect" onClick={() => go("inspect/demo")}><Play /> <span>Run the live demo</span></button>
            <button className="btn btn-xl" data-magnetic="" onClick={() => blinkTo("#/engine", "Engine")}><Layers /> How the engine works</button>
          </div>
        </div>
      </section>
    </div>
  );
}
