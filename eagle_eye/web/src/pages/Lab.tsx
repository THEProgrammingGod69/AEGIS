import { AnimatePresence, motion } from "framer-motion";
import { Flip } from "gsap/Flip";
import { CheckCircle2, CloudOff, Compass, FlaskRound, Gauge, Microscope, Play, RotateCcw, ShieldQuestion, Sparkles, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Running } from "../components/Running";
import { Count, Seg, StatusBadge, useToast } from "../components/ui";
import SWEEP from "../data/angle_sweep.json";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { api, followJob, url, useCanLive } from "../lib/api";
import { useAsync } from "../lib/hooks";
import { NEUTRAL, PRESETS, describe, loadImage, render, toFile, type Perturb } from "../lib/perturb";
import type { JobView, RunMeta } from "../lib/types";

gsap.registerPlugin(Flip);

/* ---------------- #34 PASS → REVIEW migration ---------------- */
interface SweepRow { angle: number; mode: "flat" | "perspective"; pass: number; fail: number; review: number; not_in_view: number }
const SW = SWEEP as unknown as { angles: number[]; rows: SweepRow[]; note: string; engine_version: string };
const DOTS = 50; // each dot is 2% of the judged items
const COLS = [
  { key: "PASS", label: "PASS", c: "var(--pass)" },
  { key: "REVIEW", label: "REVIEW · re-photo", c: "var(--review-bar)" },
  { key: "FAIL", label: "FAIL", c: "var(--fail)" },
] as const;

function split(r: SweepRow | undefined) {
  if (!r) return { PASS: DOTS, REVIEW: 0, FAIL: 0 };
  const judged = Math.max(1, r.pass + r.review + r.fail);
  const FAIL = r.fail ? Math.max(1, Math.round((DOTS * r.fail) / judged)) : 0;
  const REVIEW = r.review ? Math.max(1, Math.round((DOTS * r.review) / judged)) : 0;
  return { PASS: DOTS - REVIEW - FAIL, REVIEW, FAIL };
}

/** As the photo gets worse, findings move to REVIEW (re-photo), never to a false FAIL. Each finding is a dot; when the
 *  camera angle changes, verdicts are recomputed from the measured sweep and the dots Flip between columns. */
function Migration() {
  const [ai, setAi] = useState(0);
  const [mode, setMode] = useState<"flat" | "perspective">("perspective");
  const scope = useRef<HTMLDivElement>(null);
  const flip = useRef<Flip.FlipState | null>(null);
  const row = SW.rows.find((r) => r.angle === SW.angles[ai] && r.mode === mode);
  const base = split(SW.rows.find((r) => r.angle === SW.angles[0] && r.mode === mode));
  const now = split(row);
  const moved = Math.max(0, now.REVIEW - base.REVIEW);
  const colOf = (i: number) => (i < now.PASS ? "PASS" : i < now.PASS + now.REVIEW ? "REVIEW" : "FAIL");
  const change = (fn: () => void) => {
    if (!calm() && scope.current) flip.current = Flip.getState(scope.current.querySelectorAll(".lab-dot"));
    fn();
  };
  useGSAP(() => {
    const st = flip.current;
    flip.current = null;
    if (!st) return;
    Flip.from(st, {
      targets: scope.current!.querySelectorAll(".lab-dot"), duration: 0.6, ease: "ee", stagger: 0.008, absolute: true,
      onComplete: () => void gsap.fromTo(scope.current!.querySelectorAll(".lab-col.review .lab-dot.moved"), { scale: 1.6 }, { scale: 1, duration: 0.4, ease: "back.out(2)" }),
    });
  }, { scope, dependencies: [ai, mode] });

  return (
    <div className="card pad migration" ref={scope}>
      <div className="card-head">
        <div>
          <div className="card-title"><Compass /> As the camera turns, findings move to REVIEW, never to FAIL</div>
          <div className="card-sub">Measured: {SW.note.toLowerCase()} (engine {SW.engine_version}). Each dot is 2% of the items the engine judged; items outside the view are not judged and not shown.</div>
        </div>
        <Seg value={mode} onChange={(v) => change(() => setMode(v))} options={[{ value: "flat", label: "Flat registration" }, { value: "perspective", label: "With perspective search" }]} />
      </div>
      <div className="migration-ctl">
        <label className="ctl grow">
          <span className="row between tiny"><span className="muted">Camera turned sideways</span><b className="mono">{SW.angles[ai]}°</b></span>
          <input className="range" type="range" min={0} max={SW.angles.length - 1} step={1} value={ai}
            onChange={(e) => change(() => setAi(+e.target.value))} style={{ ["--p" as string]: `${(ai / (SW.angles.length - 1)) * 100}%` }} aria-label="Camera angle" />
          <span className="row between tiny faint">{SW.angles.map((a) => <span key={a}>{a}°</span>)}</span>
        </label>
        <div className="migration-count">
          <b className="mono"><Count value={moved} /></b>
          <span>dots moved to REVIEW,<br />not PASS</span>
        </div>
        <div className="migration-count safe">
          <b className="mono">{now.FAIL}</b>
          <span>false FAILs<br />(no fault planted)</span>
        </div>
      </div>
      <div className="lab-cols">
        {COLS.map((c) => (
          <div key={c.key} className={`lab-col ${c.key.toLowerCase()}`} style={{ ["--c" as string]: c.c }}>
            <div className="lab-col-head mono"><span>{c.label}</span><b>{now[c.key]}</b></div>
            <div className="lab-dots">
              {Array.from({ length: DOTS }, (_, i) => i).filter((i) => colOf(i) === c.key).map((i) => (
                <i key={i} className={`lab-dot${c.key === "REVIEW" && i < base.PASS ? " moved" : ""}`} data-flip-id={`dot-${i}`} />
              ))}
              {c.key === "FAIL" && now.FAIL === 0 && <span className="lab-empty tiny">empty at every angle: an unreadable photo is never a guessed FAIL</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface Trial {
  id: string;
  label: string;
  p: Perturb;
  meta: RunMeta;
  expected: string[];
  caught: string[];
  missed: string[];
  falseAlarms: string[];
  reviews: string[];
}

const SLIDERS: { k: keyof Perturb; label: string; min: number; max: number; step: number; fmt: (v: number) => string }[] = [
  { k: "rotate", label: "Camera tilt", min: -15, max: 15, step: 1, fmt: (v) => `${v}°` },
  { k: "keystone", label: "Keystone (shot from below)", min: 0, max: 0.25, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { k: "bright", label: "Light level", min: 0.45, max: 1.4, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { k: "contrast", label: "Contrast", min: 0.6, max: 1.3, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { k: "blur", label: "Motion / focus blur", min: 0, max: 4, step: 0.1, fmt: (v) => `${v.toFixed(1)} px` },
  { k: "noise", label: "Sensor noise", min: 0, max: 30, step: 1, fmt: (v) => `σ ${v}` },
  { k: "warm", label: "Colour cast", min: -1, max: 1, step: 0.05, fmt: (v) => (v === 0 ? "none" : v > 0 ? `warm ${Math.round(v * 100)}%` : `cool ${Math.round(-v * 100)}%`) },
  { k: "glare", label: "Glare on the door glass", min: 0, max: 1, step: 0.05, fmt: (v) => `${Math.round(v * 100)}%` },
  { k: "quality", label: "JPEG quality", min: 0.3, max: 0.95, step: 0.01, fmt: (v) => `${Math.round(v * 100)}` },
];

function score(meta: RunMeta, expected: string[], label: string, p: Perturb): Trial {
  const fails = meta.issues.filter((i) => i.result === "FAIL").map((i) => i.id);
  const reviews = meta.issues.filter((i) => i.result === "REVIEW").map((i) => i.id);
  return {
    id: meta.id, label, p, meta, expected,
    caught: expected.filter((e) => fails.includes(e)), missed: expected.filter((e) => !fails.includes(e)),
    falseAlarms: fails.filter((f) => !expected.includes(f)), reviews,
  };
}

export function Lab() {
  const toast = useToast();
  const live = useCanLive();
  const samples = useAsync(api.samples);
  const [sample, setSample] = useState("01");
  const [p, setP] = useState<Perturb>(PRESETS[1].p);
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [preview, setPreview] = useState("");
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [trials, setTrials] = useState<Trial[]>([]);
  const stop = useRef(false);
  const s = samples.data?.find((x) => x.id === sample);
  const expected = useMemo(() => (s?.issues ?? []).filter((i) => i.result === "FAIL").map((i) => i.id), [s]);

  useEffect(() => {
    let alive = true;
    setImg(null);
    loadImage(url.sampleFull(sample)).then((i) => alive && setImg(i)).catch(() => toast("error", "Could not load the sample photo"));
    return () => { alive = false; };
  }, [sample, toast]);

  useEffect(() => {
    if (!img) return;
    const t = setTimeout(() => setPreview(render(img, p, 760).toDataURL("image/jpeg", p.quality)), 60);
    return () => clearTimeout(t);
  }, [img, p]);

  const runOne = async (pp: Perturb, label: string) => {
    if (!img) throw new Error("Photo not loaded yet");
    const file = await toFile(render(img, pp), pp, `robustness_${sample}_${label.toLowerCase().replace(/\W+/g, "-")}.jpg`);
    const j = await api.inspect({ photo: file, sample: null, engine: "legacy" });
    setJob(j);
    const done = await followJob(j.id, setJob);
    if (done.status === "error") throw new Error(done.error ?? "Inspection failed");
    const meta = (await api.run(done.run_id!)).meta;
    const t = score(meta, expected, label, pp);
    setTrials((x) => [t, ...x]);
    return t;
  };

  const single = async () => {
    setBusy("single");
    try {
      await runOne(p, "Custom");
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setBusy(null);
      setJob(null);
    }
  };

  const sweep = async () => {
    setBusy("sweep");
    stop.current = false;
    try {
      for (const pr of [{ key: "clean", label: "Clean", p: NEUTRAL }, ...PRESETS]) {
        if (stop.current) break;
        setP(pr.p);
        await runOne(pr.p, pr.label);
      }
      toast("ok", "Stress sweep finished");
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setBusy(null);
      setJob(null);
    }
  };

  const totals = trials.reduce((a, t) => ({ fa: a.fa + t.falseAlarms.length, rv: a.rv + t.reviews.length, c: a.c + t.caught.length, e: a.e + t.expected.length }), { fa: 0, rv: 0, c: 0, e: 0 });

  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">Robustness Lab</span>
          <h1>Make the photo worse. Watch it refuse to guess.</h1>
          <p>Real shop-floor photos are tilted, dim, blurred and full of glare. Degrade a sample in the browser, send it to the live engine and score the result against the answer key. The design goal: as the photo gets worse, findings move to <b>REVIEW</b> (re-photo), never to a false FAIL.</p>
        </div>
        <Seg value={sample} onChange={(v) => { setSample(v); }} options={(samples.data ?? []).map((x) => ({ value: x.id, label: x.id, title: x.title }))} />
      </div>

      {!live && (
        <div className="callout info"><CloudOff /><span>The Robustness Lab sends every degraded photo to the live engine. Switch to the live engine (top right) or start it locally to run trials; the preview works either way.</span></div>
      )}

      <div className="lab-grid">
        <div className="card lab-preview">
          <div className="viewer-toolbar">
            <span className="tag accent">Sample {sample}</span>
            <span className="tiny faint ellipsis">{describe(p)}</span>
          </div>
          <div className="lab-img">
            {preview ? <img src={preview} alt="Degraded cabinet photo preview" /> : <div className="skeleton" style={{ position: "absolute", inset: 0 }} />}
          </div>
          <div className="tiny faint" style={{ padding: "10px 14px" }}>Answer key: {expected.length ? expected.join(" · ") : "no faults (a correct cabinet)"}</div>
        </div>

        <div className="stack" style={{ ["--gap" as string]: "16px" }}>
          <div className="card pad">
            <div className="card-head">
              <div className="card-title"><FlaskRound /> Camera conditions</div>
              <button className="btn btn-sm btn-ghost" onClick={() => setP(NEUTRAL)}><RotateCcw /> Reset</button>
            </div>
            <div className="row wrap" style={{ ["--gap" as string]: "6px", marginBottom: 14 }}>
              {PRESETS.map((pr) => <button key={pr.key} className="chip" aria-pressed={JSON.stringify(pr.p) === JSON.stringify(p)} onClick={() => setP(pr.p)}>{pr.label}</button>)}
            </div>
            <div className="lab-sliders">
              {SLIDERS.map((sl) => {
                const v = p[sl.k];
                return (
                  <label key={sl.k} className="ctl">
                    <span className="row between tiny"><span className="muted">{sl.label}</span><b className="mono">{sl.fmt(v)}</b></span>
                    <input className="range" type="range" min={sl.min} max={sl.max} step={sl.step} value={v} onChange={(e) => setP({ ...p, [sl.k]: +e.target.value })}
                      style={{ ["--p" as string]: `${((v - sl.min) / (sl.max - sl.min)) * 100}%` }} />
                  </label>
                );
              })}
            </div>
            <div className="row wrap" style={{ ["--gap" as string]: "8px", marginTop: 14 }}>
              <button className="btn btn-primary btn-lg grow" disabled={!live || !!busy || !img} onClick={single}><Play /> Inspect this photo</button>
              <button className="btn btn-lg grow" disabled={!live || !!busy || !img} onClick={sweep} title="Clean → Mild → Moderate → Hard → Extreme"><Gauge /> Stress sweep (5 runs)</button>
              {busy === "sweep" && <button className="btn btn-lg btn-ghost" onClick={() => { stop.current = true; }}>Stop after this run</button>}
            </div>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 20 }}><Migration /></div>

      {busy && job && (
        <div style={{ marginTop: 20 }}>
          <Running job={job} photo={preview} enabled={["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"]} title={`Robustness trial · ${describe(p)}`} />
        </div>
      )}

      <AnimatePresence>
        {trials.length > 0 && (
          <motion.div className="card pad" style={{ marginTop: 20 }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Microscope /> Trials</div>
                <div className="card-sub">{totals.c}/{totals.e} planted faults caught · <b style={{ color: totals.fa ? "var(--fail)" : "var(--pass)" }}>{totals.fa} false alarms</b> · {totals.rv} items sent to REVIEW</div>
              </div>
              <button className="btn btn-sm btn-ghost" onClick={() => setTrials([])}>Clear</button>
            </div>
            <div className="trials">
              {trials.map((t) => {
                const clean = !t.falseAlarms.length;
                const weak = t.meta.warnings?.some((w) => w.code === "weak_registration");
                return (
                  <a key={t.id} href={`#/run/${t.id}`} className="trial" style={{ ["--c" as string]: clean ? "var(--pass)" : "var(--fail)" }}>
                    <div className="row between">
                      <b>{t.label}</b>
                      <StatusBadge s={t.meta.verdict.label} />
                    </div>
                    <div className="tiny faint ellipsis" title={describe(t.p)}>{describe(t.p)}</div>
                    <div className="trial-stats">
                      <span><CheckCircle2 size={13} style={{ color: "var(--pass)" }} /> {t.caught.length}/{t.expected.length} caught</span>
                      <span>{clean ? <CheckCircle2 size={13} style={{ color: "var(--pass)" }} /> : <XCircle size={13} style={{ color: "var(--fail)" }} />} {t.falseAlarms.length} false alarm{t.falseAlarms.length === 1 ? "" : "s"}</span>
                      <span><ShieldQuestion size={13} style={{ color: "var(--review)" }} /> {t.reviews.length} review</span>
                      <span className="faint">{t.meta.timing.total.toFixed(1)} s</span>
                    </div>
                    {weak && <div className="tiny" style={{ color: "var(--review)" }}>Photo did not register against the drawing: FAIL is blocked, everything goes to REVIEW.</div>}
                    {t.missed.length > 0 && <div className="tiny faint">Not FAIL: {t.missed.join(", ")}</div>}
                  </a>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="card pad small muted row" style={{ marginTop: 20, ["--gap" as string]: "10px", alignItems: "flex-start" }}>
        <Sparkles size={18} style={{ flexShrink: 0, color: "var(--accent)" }} />
        <span>Each trial is a real run of the engine on the degraded photo: registration, all five plug-in checks and the consensus rules. Trials land in History like any inspection, so the proof crops and reports are one click away.</span>
      </div>
    </div>
  );
}
