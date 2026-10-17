import { motion } from "framer-motion";
import { Camera, Check, Download, FileSpreadsheet, FileText, ImageIcon, ListChecks, Play, Puzzle, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { DropZone } from "../components/DropZone";
import { Running } from "../components/Running";
import { StatusBadge, useToast } from "../components/ui";
import { STATIC, api, followJob, url } from "../lib/api";
import { LIVE_ONLY, REPO_URL } from "../lib/static";
import { CHECK_TITLE } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { go } from "../lib/router";
import type { JobView, Sample } from "../lib/types";

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

function InputRow({ icon, label, accept, file, onFile, demo, dl }: {
  icon: React.ReactNode; label: string; accept: string; file: File | null; onFile: (f: File | null) => void; demo?: string; dl: string;
}) {
  if (STATIC)
    return (
      <div className="input-row">
        <div className="drop compact has" style={{ cursor: "default", flex: 1 }}>
          <div className="drop-icon">{icon}</div>
          <div className="drop-text"><div className="drop-title">{label}</div><div className="drop-hint mono">{demo}</div></div>
        </div>
        <a className="btn btn-sm btn-icon btn-ghost" href={dl} title={`Download ${demo}`}><Download /></a>
      </div>
    );
  return (
    <div className="input-row">
      <DropZone compact accept={accept} file={file} onFile={onFile} title={label} icon={icon}
        hint={demo ? <>Demo: <span className="mono">{demo}</span></> : "Drop or click"} />
      {!file && (
        <a className="btn btn-sm btn-icon btn-ghost" href={dl} title={`Download ${demo}`} onClick={(e) => e.stopPropagation()}>
          <Download />
        </a>
      )}
    </div>
  );
}

export function Inspect({ autoDemo }: { autoDemo: boolean }) {
  const toast = useToast();
  const samples = useAsync(api.samples);
  const checks = useAsync(api.checks);
  const inputs = useAsync(api.inputs);
  const [photo, setPhoto] = useState<File | null>(null);
  const [sample, setSample] = useState<string>("01");
  const [ga, setGa] = useState<File | null>(null);
  const [wires, setWires] = useState<File | null>(null);
  const [checklist, setChecklist] = useState<File | null>(null);
  const [enabled, setEnabled] = useState<string[] | null>(null);
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);

  const allChecks = checks.data?.map((c) => c.name) ?? ["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"];
  const on = enabled ?? allChecks;
  const photoUrl = useMemo(() => (photo ? URL.createObjectURL(photo) : url.sample(sample, 1400)), [photo, sample]);
  useEffect(() => () => { if (photoUrl.startsWith("blob:")) URL.revokeObjectURL(photoUrl); }, [photoUrl]);
  const activeSample = samples.data?.find((s) => s.id === sample);

  const start = async (override?: { sample?: string }) => {
    if (busy) return;
    setBusy(true);
    setJob(null);
    try {
      const j = await api.inspect({ photo: override ? null : photo, sample: override?.sample ?? sample, ga, wires, checklist, checks: on });
      setJob(j);
      const done = await followJob(j.id, setJob);
      if (done.status === "error") throw new Error(done.error ?? "Inspection failed");
      go(`run/${done.run_id}`);
    } catch (e) {
      toast("error", (e as Error).message);
      setJob(null);
      setBusy(false);
    }
  };

  useEffect(() => {
    if (autoDemo && !started.current) {
      started.current = true;
      window.history.replaceState(null, "", "#/inspect");
      start({ sample: "01" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoDemo]);

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
        <Running job={job} photo={photoUrl} enabled={on} title={photo ? photo.name : activeSample ? `Sample ${activeSample.id} · ${activeSample.title}` : "Emerson's example"} />
      </div>
    );
  }

  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">Inspect</span>
          <h1>Photo in. Filled checklist with proof out.</h1>
          <p>Drop a cabinet photo or pick a sample. Leave the engineering inputs empty to use the demo drawing set (GA drawing, wire list, QC checklist for cabinet EE-DEMO-01).</p>
        </div>
        <button className="btn btn-primary btn-xl" onClick={() => start()}>
          <Play /> Inspect <kbd style={{ marginLeft: 4, background: "rgba(4,18,28,.15)", color: "inherit", borderColor: "rgba(4,18,28,.25)" }}>Ctrl ↵</kbd>
        </button>
      </div>

      {STATIC && (
        <div className="callout info">
          <Sparkles />
          <span>{LIVE_ONLY} <a href={REPO_URL} target="_blank" rel="noreferrer">Get the code →</a></span>
        </div>
      )}

      <div className="setup">
        <div className="stack" style={{ ["--gap" as string]: "18px" }}>
          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Camera /> Cabinet photo</div>
                <div className="card-sub">HD photo of the whole backplate, JPG or PNG. Phone photos are auto-rotated and resized.</div>
              </div>
            </div>
            <div className="photo-pick">
              <div className="photo-preview">
                <img src={photoUrl} alt="Selected cabinet photo" />
                <span className="photo-preview-tag">{photo ? "Your upload" : `Sample ${sample}`}</span>
              </div>
              <div className="stack" style={{ ["--gap" as string]: "12px" }}>
                {!STATIC && <DropZone accept=".jpg,.jpeg,.png" file={photo} onFile={setPhoto} preview title="Drop your own cabinet photo" hint="…or pick one of the samples below" icon={<ImageIcon />} />}
                {activeSample && !photo && (
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

          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Sparkles /> Sample photos</div>
                <div className="card-sub">Generated by Fault Forge to copy Emerson's example layout. Each has a known answer key.</div>
              </div>
            </div>
            <div className="samples">
              {samples.data?.map((s) => (
                <SampleCard key={s.id} s={s} active={!photo && s.id === sample} onClick={() => { setPhoto(null); setSample(s.id); }} />
              )) ?? Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 230 }} />)}
            </div>
          </motion.div>
        </div>

        <div className="stack" style={{ ["--gap" as string]: "18px" }}>
          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><FileText /> Engineering inputs</div>
                <div className="card-sub">The drawing is the ground truth: it defines every item to check.</div>
              </div>
            </div>
            {ga ? (
              <div className="card flat pad small muted">Custom drawing <span className="mono">{ga.name}</span>: its device tags, boxes, rails and terminals are parsed when you press Inspect.</div>
            ) : (
              <div className="ga-preview">
                <img src={url.gaPreview()} alt="GA drawing preview" />
                <div className="ga-preview-cap">
                  <span className="mono tiny">{inputs.data?.ga?.name ?? "GA_EE-DEMO-01.pdf"}</span>
                  <span className="tiny faint">12 devices · 8 terminals · 1 rail</span>
                </div>
              </div>
            )}
            <div className="stack" style={{ ["--gap" as string]: "8px", marginTop: 14 }}>
              <InputRow icon={<FileText />} label="GA drawing (vector PDF)" accept=".pdf" file={ga} onFile={setGa} demo={inputs.data?.ga?.name} dl={url.input("ga")} />
              <InputRow icon={<FileSpreadsheet />} label="Wire & label list (Excel)" accept=".xlsx" file={wires} onFile={setWires} demo={inputs.data?.wires?.name} dl={url.input("wires")} />
              <InputRow icon={<ListChecks />} label="QC checklist (Excel)" accept=".xlsx" file={checklist} onFile={setChecklist} demo={inputs.data?.checklist?.name} dl={url.input("checklist")} />
            </div>
            <div className="tiny faint" style={{ marginTop: 12 }}>
              A photo of another cabinet only works with that cabinet's own GA drawing and wire list.
            </div>
          </motion.div>

          <motion.div className="card pad" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
            <div className="card-head">
              <div>
                <div className="card-title"><Puzzle /> Plug-in checks</div>
                <div className="card-sub">Each check is one class with <code>@check("NAME")</code>. Toggle to see the root-cause logic adapt.</div>
              </div>
            </div>
            <div className="checks">
              {(checks.data ?? allChecks.map((n) => ({ name: n, title: CHECK_TITLE[n], question: "", doc: "", builtin: true }))).map((c) => {
                const active = on.includes(c.name);
                return (
                  <button key={c.name} className={`check-tile${active ? " on" : ""}`} aria-pressed={active}
                    disabled={STATIC} title={STATIC ? "Recorded runs use all five checks; toggling needs the live engine" : undefined}
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

          <button className="btn btn-primary btn-xl btn-block" onClick={() => start()} disabled={on.length === 0}>
            <Play /> Inspect {photo ? photo.name : `sample ${sample}`}
          </button>
        </div>
      </div>
    </div>
  );
}
