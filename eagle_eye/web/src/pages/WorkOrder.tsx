import { ArrowLeft, CheckSquare, ClipboardList, Printer, RefreshCcw, Square, Timer, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ProofCrop } from "../components/ProofCard";
import { Marker, StatusBadge } from "../components/ui";
import { api } from "../lib/api";
import { fixFor } from "../lib/fixes";
import { CHECK_TITLE, isIssue, runDate, shortId, statusOf } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { finalResult, inspectorName } from "../lib/reviews";
import { go } from "../lib/router";

/** Printable technician job sheet: every confirmed fault as a numbered fix with proof, location and sign-off. */
export function WorkOrder({ id }: { id: string }) {
  const { data: p, error } = useAsync(() => api.run(id), [id]);
  const key = `ee_wo_${id}`;
  const [done, setDone] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem(key) ?? "{}");
    } catch {
      return {};
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(done));
    } catch {
      /* private window */
    }
  }, [done, key]);

  const steps = useMemo(() => {
    if (!p) return [];
    return p.results
      .filter((it) => isIssue(it) && statusOf(it) !== "CLOSED")
      .map((it) => ({ it, final: finalResult(it, p.meta) }))
      .filter((x) => x.final === "FAIL" || x.final === "REVIEW")
      .sort((a, b) => (a.it.marker ?? 0) - (b.it.marker ?? 0))
      .map((x) => ({ ...x, fix: fixFor({ ...x.it, result: x.final }, p) }));
  }, [p]);
  const cleared = p ? p.results.filter((it) => isIssue(it) && it.result !== "PASS" && finalResult(it, p.meta) === "PASS") : [];

  if (error) return <div className="main"><div className="card pad empty">Could not load run: {error}</div></div>;
  if (!p) return <div className="main"><div className="skeleton" style={{ height: 900 }} /></div>;

  const fixes = steps.filter((s) => s.fix.kind === "fix");
  const minutes = steps.reduce((a, s) => a + s.fix.minutes, 0);
  const nDone = steps.filter((s) => done[s.it.id]).length;
  const wo = `WO-${p.meta.cabinet}-${shortId(id)}`;
  const geo = { photoSize: p.photo_size, sizeMm: p.size_mm };

  return (
    <div className="main wo-page">
      <div className="row between wrap no-print" style={{ marginBottom: 18, ["--gap" as string]: "10px" }}>
        <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
          <button className="btn btn-sm btn-ghost" onClick={() => go(`run/${id}`)}><ArrowLeft /> Back to the inspection</button>
          <span className="tiny faint">{nDone}/{steps.length} ticked on this device</span>
        </div>
        <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
          <button className="btn" onClick={() => window.print()}><Printer /> Print / save PDF</button>
          <button className="btn btn-primary" onClick={() => { go(`run/${id}`); setTimeout(() => document.getElementById("recheck")?.scrollIntoView({ behavior: "smooth", block: "center" }), 450); }}>
            <RefreshCcw /> Fixed: re-check
          </button>
        </div>
      </div>

      <article className="wo-sheet">
        <header className="wo-head">
          <div>
            <div className="wo-brand">EAGLE EYE · QC WORK ORDER</div>
            <h1>{wo}</h1>
            <div className="wo-sub">Cabinet <b>{p.meta.cabinet}</b> · {p.meta.label} · inspected {runDate(p.meta.created)} · run {id}</div>
          </div>
          <div className="wo-stamp" data-v={steps.length ? "hold" : "pass"}>{steps.length ? "HOLD · DO NOT SHIP" : "NO ACTION · READY"}</div>
        </header>

        <div className="wo-summary">
          <div><b>{fixes.length}</b><span>fixes</span></div>
          <div><b>{steps.length - fixes.length}</b><span>zones to re-photo</span></div>
          <div><b>~{minutes}</b><span>min estimated</span></div>
          <div><b>{p.meta.items}</b><span>items checked against the drawing</span></div>
        </div>

        {steps.length === 0 && (
          <div className="wo-empty">Every item the GA drawing and wire list expect was verified. Nothing to fix.</div>
        )}

        <ol className="wo-steps">
          {steps.map(({ it, fix, final }) => (
            <li key={it.id} className={`wo-step${done[it.id] ? " done" : ""}`}>
              <div className="wo-step-num"><Marker n={it.marker ?? "·"} s={final} lg /></div>
              <div className="wo-step-body">
                <div className="row between wrap" style={{ ["--gap" as string]: "8px" }}>
                  <h3>{fix.action}</h3>
                  <div className="row" style={{ ["--gap" as string]: "6px" }}>
                    <span className="wo-pill">{CHECK_TITLE[it.check] ?? it.check}</span>
                    <StatusBadge s={final} />
                    <span className="wo-pill"><Timer size={12} /> ~{fix.minutes} min</span>
                  </div>
                </div>
                <p>{fix.detail}</p>
                <div className="wo-meta">
                  <span><b>Where</b> {fix.where}</span>
                  <span><b>Item</b> <span className="mono">{it.id}</span></span>
                  <span><b>Drawing</b> <span className="mono">{it.expected}</span></span>
                  <span><b>Found</b> <span className="mono">{it.found}</span></span>
                  {p.meta.reviews?.[it.id] && <span><b>Inspector</b> {p.meta.reviews[it.id].by}: {p.meta.reviews[it.id].note || p.meta.reviews[it.id].decision}</span>}
                </div>
              </div>
              <div className="wo-crops">
                <figure><div className="wo-crop drawing"><ProofCrop run={id} it={it} kind="expected" geo={geo} /></div><figcaption>Drawing</figcaption></figure>
                <figure><div className="wo-crop"><ProofCrop run={id} it={it} kind="found" geo={geo} /></div><figcaption>Photo</figcaption></figure>
              </div>
              <button className="wo-check" onClick={() => setDone({ ...done, [it.id]: !done[it.id] })} aria-pressed={!!done[it.id]} title="Mark as done">
                {done[it.id] ? <CheckSquare /> : <Square />}
                <span>Done</span>
                <i>Initials ______</i>
              </button>
            </li>
          ))}
        </ol>

        {cleared.length > 0 && (
          <div className="wo-note">
            <ClipboardList size={15} /> Cleared by the inspector (no action): {cleared.map((it) => `${it.id} (${p.meta.reviews?.[it.id]?.note || "checked on the cabinet"})`).join(" · ")}
          </div>
        )}

        <div className="wo-after">
          <Wrench size={16} />
          <div>
            <b>When the fixes are done</b>
            <p>Photograph the whole backplate again and run <b>Re-check</b> on this inspection. Fixed items close automatically (CLOSED), anything still wrong stays OPEN, and anything newly broken is flagged as a REGRESSION.</p>
          </div>
        </div>

        <footer className="wo-sign">
          <div><span>Technician</span><i /></div>
          <div><span>QC inspector</span><i>{inspectorName() !== "Inspector" ? inspectorName() : ""}</i></div>
          <div><span>Date</span><i /></div>
        </footer>
        <div className="wo-fine">Generated by EAGLE EYE {p.meta.engine} from GA drawing {p.meta.inputs.ga.name} and wire list {p.meta.inputs.wires.name}. Every fix is backed by an expected-vs-found crop; FAIL is only raised when independent evidence agrees.</div>
      </article>
    </div>
  );
}
