import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, CloudOff, FlaskRound, Gauge, Microscope, Play, RotateCcw, ShieldQuestion, Sparkles, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Running } from "../components/Running";
import { Seg, StatusBadge, useToast } from "../components/ui";
import { api, followJob, url, useCanLive } from "../lib/api";
import { useAsync } from "../lib/hooks";
import { NEUTRAL, PRESETS, describe, loadImage, render, toFile, type Perturb } from "../lib/perturb";
import type { JobView, RunMeta } from "../lib/types";

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
    const j = await api.inspect({ photo: file, sample: null });
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
