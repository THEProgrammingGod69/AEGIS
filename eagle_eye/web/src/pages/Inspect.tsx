import { motion } from "framer-motion";
import { Aperture, Camera, Check, CloudOff, Download, Factory, FileSpreadsheet, FileText, Fingerprint, Gauge, ImageIcon, ListChecks, Play, Puzzle, RefreshCw, Sparkles, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CameraCapture } from "../components/Camera";
import { DropZone } from "../components/DropZone";
import { Running } from "../components/Running";
import { Seg, StatusBadge, useToast } from "../components/ui";
import { STATIC, api, followJob, url, useCanLive } from "../lib/api";
import { pingEngine, useEngine } from "../lib/cloud";
import { LIVE_ONLY } from "../lib/static";
import { CHECK_TITLE } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { analyzePhoto, type PhotoQuality } from "../lib/quality";
import { go } from "../lib/router";
import type { JobView, Preset, Sample } from "../lib/types";

/** Real drawing set + photos the engine holds (data/emerson locally, a mounted volume in the cloud). */
function PresetCard({ presets, onRun, disabled }: { presets: Preset[]; onRun: (p: Preset, file: string) => void; disabled: boolean }) {
  if (!presets.length) return null;
  return (
    <>
      {presets.map((p) => (
        <motion.div key={p.id} className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
          <div className="card-head">
            <div>
              <div className="card-title"><Factory /> {p.title} · real cabinet</div>
              <div className="card-sub">
                Drawing: <span className="mono">{p.ga}</span>{p.cabinet ? ` · cabinet ${p.cabinet}` : ""}.
                Inspect one of the paired real photographs with local OCR and drawing geometry. Unreadable or unseen items stay unverified.
              </div>
            </div>
          </div>
          <div className="samples">
            {p.photos.map((ph) => (
              <button key={ph.file} className="sample" disabled={disabled} onClick={() => onRun(p, ph.file)} title={ph.content}>
                <div className="sample-img"><img src={url.presetPhoto(p.id, ph.file, 360)} alt={ph.file} loading="lazy" /></div>
                <div className="sample-body">
                  <div className="sample-title mono" style={{ fontSize: 12 }}>{ph.file.replace(/^IMG_\d+_/, "").replace(/\.[a-z]+$/i, "")}</div>
                  <div className="sample-sub">{ph.content || "Inspect this photo"}</div>
                </div>
              </button>
            ))}
          </div>
        </motion.div>
      ))}
    </>
  );
}

export function SampleCard({ s, active, onClick }: { s: Sample; active: boolean; onClick: () => void }) {
  const c = s.counts;
  return (
    <button className={`sample${active ? " active" : ""}`} onClick={onClick} aria-pressed={active}>
      <div className="sample-img">
        <img src={url.sample(s.id, 360)} alt={s.title} loading="lazy" />
        <span className="sample-id mono">{s.id}</span>
        {active && <span className="sample-check"><Check size={13} strokeWidth={3} /></span>}
      </div>
      <div className="sample-body">
        <div className="sample-title">{s.title}</div>
        <div className="sample-sub">{s.subtitle}</div>
        <div className="row wrap" style={{ ["--gap" as string]: "5px", marginTop: 8 }}>
          {c.FAIL > 0 ? <StatusBadge s="FAIL" label={`${c.FAIL} FAIL`} /> : <StatusBadge s="PASS" label="ALL PASS" />}
          {c.SKIP > 0 && <StatusBadge s="SKIP" label={`${c.SKIP} SKIP`} />}
        </div>
      </div>
    </button>
  );
}

const LEVEL_C = { good: "var(--pass)", warn: "var(--review)", bad: "var(--fail)" } as const;

/** Capture assistant: sharpness, exposure, glare... checked in the browser before a run is spent on a bad photo. */
function QualityPanel({ q }: { q: PhotoQuality | null }) {
  if (!q) return <div className="skeleton" style={{ height: 74 }} />;
  return (
    <div className="quality">
      <div className="quality-score" style={{ ["--c" as string]: LEVEL_C[q.level] }}>
        <Gauge size={15} />
        <b className="mono">{q.score}</b>
        <span className="tiny faint">photo score</span>
      </div>
      <div className="quality-checks">
        {q.checks.map((c) => (
          <span key={c.key} className="quality-chip tip" data-tip={c.tip} style={{ ["--c" as string]: LEVEL_C[c.level] }}>
            <i />{c.label} <b className="mono">{c.value}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

function InputRow({ icon, label, accept, file, onFile, demo, dl, live }: {
  icon: React.ReactNode; label: string; accept: string; file: File | null; onFile: (f: File | null) => void; demo?: string; dl?: string; live: boolean;
}) {
  if (!live)
    return (
      <div className="input-row">
        <div className="drop compact has" style={{ cursor: "default", flex: 1 }}>
          <div className="drop-icon">{icon}</div>
          <div className="drop-text"><div className="drop-title">{label}</div><div className="drop-hint mono">{demo}</div></div>
        </div>
        {dl && <a className="btn btn-sm btn-icon btn-ghost" href={dl} title={`Download ${demo}`}><Download /></a>}
      </div>
    );
  return (
    <div className="input-row">
      <DropZone compact accept={accept} file={file} onFile={onFile} title={label} icon={icon}
        hint={demo ? <>Demo: <span className="mono">{demo}</span></> : "Drop or click"} />
      {!file && dl && (
        <a className="btn btn-sm btn-icon btn-ghost" href={dl} title={`Download ${demo}`} onClick={(e) => e.stopPropagation()}>
          <Download />
        </a>
      )}
    </div>
  );
}

export function Inspect({ autoDemo, autoSample = null }: { autoDemo: boolean; autoSample?: string | null }) {
  const toast = useToast();
  const live = useCanLive();
  const eng = useEngine();
  const samples = useAsync(api.samples);
  const checks = useAsync(api.checks);
  const inputs = useAsync(api.inputs);
  const presets = useAsync(api.presets, [live]);
  const [presetTitle, setPresetTitle] = useState<string | null>(null);
  const [jobPhoto, setJobPhoto] = useState("");
  const [inputMode, setInputMode] = useState<"real" | "demo">(autoDemo || autoSample ? "demo" : "real");
  const [presetId, setPresetId] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [sample, setSample] = useState<string>("01");
  const [ga, setGa] = useState<File | null>(null);
  const [wires, setWires] = useState<File | null>(null);
  const [checklist, setChecklist] = useState<File | null>(null);
  const [enabled, setEnabled] = useState<string[] | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState(false);
  const [cam, setCam] = useState(false);
  const [quality, setQuality] = useState<PhotoQuality | null>(null);
  const started = useRef(false);
  const selectedPreset = presets.data?.find((p) => p.id === presetId);

  const allChecks = checks.data?.map((c) => c.name) ?? ["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"];
  const on = enabled ?? allChecks;
  const photoUrl = useMemo(() => (photo ? URL.createObjectURL(photo) : inputMode === "demo" ? url.sample(sample, 1400) : ""), [photo, sample, inputMode]);
  useEffect(() => () => { if (photoUrl.startsWith("blob:")) URL.revokeObjectURL(photoUrl); }, [photoUrl]);
  const activeSample = samples.data?.find((s) => s.id === sample);
  const blocked = on.length === 0 || (inputMode === "real" && (!live || !photo || (!ga && !selectedPreset))) || (inputMode === "demo" && !!photo && !live);
  const inputHint = inputMode === "demo" ? "Synthetic demo · EE-DEMO-01 · generated photos only"
    : !photo ? "Choose a cabinet photo or inspect a paired real photo below."
      : !ga && !selectedPreset ? "Matching GA drawing required. Select a preset or upload the cabinet's PDF."
        : `Photo: ${photo.name} · drawing: ${selectedPreset?.ga ?? ga?.name} · local OCR and geometry`;
  useEffect(() => {
    let alive = true;
    setQuality(null);
    if (!photoUrl) return;
    analyzePhoto(photo ?? photoUrl).then((q) => alive && setQuality(q)).catch(() => alive && setQuality(null));
    return () => { alive = false; };
  }, [photo, photoUrl]);

  const start = async (override?: { sample?: string; preset?: Preset; presetPhoto?: string }) => {
    if (busy) return;
    const demo = !!override?.sample || (!override?.preset && inputMode === "demo");
    if (!on.length) { toast("error", "Select at least one inspection check."); return; }
    if (!override && inputMode === "real" && (!photo || (!ga && !selectedPreset))) {
      toast("error", !photo ? "Choose a real cabinet photo or one of the paired preset photos." : "Select the matching real cabinet drawing or upload its GA PDF before inspecting.");
      return;
    }
    if (!demo && !live) { toast("error", "Real cabinet inspection needs the local or live inspection engine. Synthetic recorded samples remain available."); return; }
    setBusy(true);
    setJob(null);
    setJobPhoto(override?.preset ? url.presetPhoto(override.preset.id, override.presetPhoto!, 1400) : override?.sample ? url.sample(override.sample, 1400) : photoUrl);
    setPresetTitle(override?.preset ? `${override.preset.title} · ${override.presetPhoto}` : null);
    try {
      const j = await api.inspect(override?.preset
        ? { preset: override.preset.id, presetPhoto: override.presetPhoto, checks: enabled ?? undefined, engine: "real" }
        : demo
          ? { photo: override ? null : photo, sample: override?.sample ?? sample, checks: on, engine: "legacy" }
          : { photo, preset: selectedPreset?.id, ga: selectedPreset ? null : ga, wires, checklist, checks: on, engine: "real" });
      setJob(j);
      const done = await followJob(j.id, setJob);
      if (done.status === "error") throw new Error(done.error ?? "Inspection failed");
      if (done.note) toast("ok", done.note);
      go(`run/${done.run_id}`);
    } catch (e) {
      toast("error", (e as Error).message);
      setJob(null);
      setBusy(false);
    }
  };

  useEffect(() => {
    const want = autoDemo ? "01" : autoSample;
    if (want && !started.current) {
      started.current = true;
      window.history.replaceState(null, "", "#/inspect");
      setSample(want);
      setInputMode("demo");
      start({ sample: want });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoDemo, autoSample]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") start();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (busy) {
    return (
      <div className="main">
        <Running job={job} photo={jobPhoto} enabled={on} title={presetTitle ?? (photo ? photo.name : activeSample ? `Sample ${activeSample.id} · ${activeSample.title}` : "Cabinet inspection")} />
      </div>
    );
  }

  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">Inspect</span>
          <h1>Photo in. Filled checklist with proof out.</h1>
          <p>Inspect a real cabinet against its matching drawing using local OCR and geometry. Generated samples have their own explicit demo mode.</p>
        </div>
        <button className="btn btn-primary btn-xl" disabled={blocked} onClick={() => start()}>
          <Play /> Inspect <kbd style={{ marginLeft: 4, background: "rgba(4,18,28,.15)", color: "inherit", borderColor: "rgba(4,18,28,.25)" }}>Ctrl ↵</kbd>
        </button>
      </div>

      <div className="card pad" style={{ marginBottom: 18 }}>
        <div className="row between wrap" style={{ gap: 14 }}>
          <div><div className="card-title">Inspection mode</div><div className="card-sub">The selected mode determines which drawing is used.</div></div>
          <Seg value={inputMode} onChange={(v) => { setInputMode(v); setPhoto(null); setEnabled(null); }} options={[
            { value: "real", label: <><Factory size={15} /> Real cabinet</>, title: "Requires the actual cabinet's matching GA drawing" },
            { value: "demo", label: <><Sparkles size={15} /> Synthetic demo</>, title: "Generated EE-DEMO-01 examples with known faults" },
          ]} />
        </div>
        <div className="small muted" style={{ marginTop: 12 }} aria-live="polite">{inputHint}</div>
      </div>

      {STATIC && live && (
        <div className="callout ok">
          <Zap />
          <span><b>Live inspection engine.</b> OCR and drawing checks run on your configured backend without a third-party AI API. Processing time depends on image detail and available CPU. Results stay in this browser.</span>
        </div>
      )}
      {STATIC && !live && (
        <div className="callout info">
          {eng.preferLive ? <CloudOff /> : <Sparkles />}
          <span>
            {eng.preferLive ? (eng.state === "checking" ? "Waking the cloud engine… samples run as recorded replays meanwhile." : LIVE_ONLY)
              : "Instant replay mode: samples replay inspections recorded from the same engine. Switch to the live engine (top right) to upload your own photo."}
          </span>
          {eng.preferLive && eng.state === "down" && <button className="btn btn-sm" onClick={() => void pingEngine()}><RefreshCw /> Retry</button>}
        </div>
      )}

      <div className="callout info">
        <Fingerprint />
        <span><b>Inspection provenance.</b> Results record the photo fingerprint, drawing and check selection. {STATIC ? "This browser retains a small preview and inspection metadata; full uploads are processed temporarily by the engine." : "The local engine retains reports and working images in its configured run directory."}</span>
      </div>

      {inputMode === "real" && <PresetCard presets={presets.data ?? []} disabled={!live || !on.length} onRun={(p, f) => start({ preset: p, presetPhoto: f })} />}

      <div className="setup">
        <div className="stack" style={{ ["--gap" as string]: "18px" }}>
          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Camera /> Cabinet photo</div>
                <div className="card-sub">{inputMode === "real" ? "Photograph the whole relevant cabinet view, then add close-ups for small labels. JPG or PNG; phone orientation is corrected." : "Generated EE-DEMO-01 photos only. Real phone photos require Real cabinet mode and their own drawing."}</div>
              </div>
            </div>
            <div className="photo-pick">
              <div className="photo-preview">
                {photoUrl ? <img src={photoUrl} alt="Selected cabinet photo" /> : <div className="empty"><Camera /><span>Choose a real cabinet photo</span></div>}
                <span className="photo-preview-tag">{photo ? "Your upload" : inputMode === "demo" ? `Synthetic sample ${sample}` : "No photo selected"}</span>
              </div>
              <div className="stack" style={{ ["--gap" as string]: "12px" }}>
                {live && <DropZone accept=".jpg,.jpeg,.png" file={photo} onFile={setPhoto} preview title={inputMode === "real" ? "Drop your real cabinet photo" : "Upload a generated demo photo"} hint={inputMode === "real" ? "Select the matching drawing on the right" : "This will use the EE-DEMO-01 demo drawing"} icon={<ImageIcon />} />}
                {live && (
                  <button className="btn btn-block" onClick={() => setCam(true)}><Aperture /> Capture with camera</button>
                )}
                {photoUrl && <QualityPanel q={quality} />}
                {inputMode === "demo" && activeSample && !photo && (
                  <div className="card flat pad sample-expect">
                    <div className="tiny faint" style={{ marginBottom: 6 }}>Planted faults (answer key)</div>
                    {activeSample.fault_text.length ? (
                      <ul>{activeSample.fault_text.map((f) => <li key={f}>{f}</li>)}</ul>
                    ) : <div className="small muted">None. A correct cabinet must come back all PASS.</div>}
                    <div className="tiny faint" style={{ marginTop: 10 }}>Expected result</div>
                    <div className="small">{activeSample.expect}</div>
                  </div>
                )}
              </div>
            </div>
          </motion.div>

          {inputMode === "demo" && <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Sparkles /> Synthetic sample photos</div>
                <div className="card-sub">Generated by Fault Forge for EE-DEMO-01. Each has a known answer key; these results do not establish real-cabinet accuracy.</div>
              </div>
            </div>
            <div className="samples">
              {samples.data?.map((s) => (
                <SampleCard key={s.id} s={s} active={!photo && s.id === sample} onClick={() => { setPhoto(null); setSample(s.id); }} />
              )) ?? Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 230 }} />)}
            </div>
          </motion.div>}
        </div>

        <div className="stack" style={{ ["--gap" as string]: "18px" }}>
          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><FileText /> Engineering inputs</div>
                <div className="card-sub">{inputMode === "real" ? "Use the GA drawing for this exact cabinet and revision. A block diagram alone may not define physical positions." : "Demo inputs apply only to the generated EE-DEMO-01 cabinet."}</div>
              </div>
            </div>
            {inputMode === "real" && <>
              <label className="small muted" htmlFor="drawing-source">Drawing source</label>
              <select id="drawing-source" className="input" style={{ marginTop: 8, marginBottom: 12, width: "100%" }} value={presetId} onChange={(e) => { setPresetId(e.target.value); if (e.target.value) setGa(null); }} disabled={!live}>
                <option value="">Upload this cabinet's GA PDF</option>
                {(presets.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.title} · {p.ga}</option>)}
              </select>
              {selectedPreset && <div className="card flat pad small muted"><b>Selected real drawing:</b> <span className="mono">{selectedPreset.ga}</span>{selectedPreset.cabinet ? ` · cabinet ${selectedPreset.cabinet}` : ""}. Use this only for photographs of that cabinet.</div>}
              {!selectedPreset && <InputRow live={live} icon={<FileText />} label="Matching GA drawing (vector PDF) · required" accept=".pdf" file={ga} onFile={setGa} />}
            </>}
            {inputMode === "real" && ga ? (
              <div className="card flat pad small muted">Custom drawing <span className="mono">{ga.name}</span>: its device tags, boxes, rails and terminals are parsed when you press Inspect.</div>
            ) : inputMode === "demo" ? (
              <div className="ga-preview">
                <img src={url.gaPreview()} alt="GA drawing preview" />
                <div className="ga-preview-cap">
                  <span className="mono tiny">{inputs.data?.ga?.name ?? "GA_EE-DEMO-01.pdf"}</span>
                  <span className="tiny faint">12 devices · 8 terminals · 1 rail</span>
                </div>
              </div>
            ) : null}
            <div className="stack" style={{ ["--gap" as string]: "8px", marginTop: 14 }}>
              {inputMode === "demo" ? <>
                <InputRow live={false} icon={<FileText />} label="Demo GA drawing" accept=".pdf" file={null} onFile={setGa} demo={inputs.data?.ga?.name} dl={url.input("ga")} />
                <InputRow live={false} icon={<FileSpreadsheet />} label="Demo wire & label list" accept=".xlsx" file={null} onFile={setWires} demo={inputs.data?.wires?.name} dl={url.input("wires")} />
                <InputRow live={false} icon={<ListChecks />} label="Demo QC checklist" accept=".xlsx" file={null} onFile={setChecklist} demo={inputs.data?.checklist?.name} dl={url.input("checklist")} />
              </> : <>
                <InputRow live={live} icon={<FileSpreadsheet />} label="Matching wire & label list (optional Excel)" accept=".xlsx" file={wires} onFile={setWires} />
                <InputRow live={live} icon={<ListChecks />} label="Matching QC checklist (optional Excel)" accept=".xlsx" file={checklist} onFile={setChecklist} />
              </>}
            </div>
            <div className="tiny faint" style={{ marginTop: 12 }}>
              A photo of another cabinet only works with that cabinet's own GA drawing and wire list.
            </div>
          </motion.div>

          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Puzzle /> Inspection checks</div>
                <div className="card-sub">Choose which checks to run. A limited check selection does not approve the whole cabinet.</div>
              </div>
            </div>
            <div className="checks">
              {(checks.data ?? allChecks.map((n) => ({ name: n, title: CHECK_TITLE[n], question: "", doc: "", builtin: true }))).map((c) => {
                const active = on.includes(c.name);
                return (
                  <button key={c.name} className={`check-tile${active ? " on" : ""}`} aria-pressed={active}
                    disabled={!live} title={!live ? "Recorded runs use all five checks; toggling needs the live engine" : undefined}
                    onClick={() => setEnabled(active ? on.filter((x) => x !== c.name) : [...on, c.name])}>
                    <span className="switch" role="switch" aria-checked={active} />
                    <div className="grow">
                      <div className="row between"><b className="mono">{c.name}</b><span className="tiny faint">{c.title}</span></div>
                      <div className="tiny muted">{c.question}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </motion.div>

          <div className="small muted" aria-live="polite">{!on.length ? "Select at least one inspection check." : inputHint}</div>
          <button className="btn btn-primary btn-xl btn-block" onClick={() => start()} disabled={blocked}>
            <Play /> {inputMode === "real" ? "Inspect real cabinet" : `Inspect synthetic ${photo ? "upload" : `sample ${sample}`}`}
          </button>
        </div>
      </div>
      <CameraCapture open={cam} onClose={() => setCam(false)} onPhoto={(f) => setPhoto(f)} />
    </div>
  );
}
