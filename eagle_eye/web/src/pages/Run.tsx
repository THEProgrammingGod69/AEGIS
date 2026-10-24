import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeft, Bot, Camera, CheckCircle2, ChevronRight, ClipboardList, Cloud, Crosshair, Download, Eye, FileJson, FileSpreadsheet, FileText, Fingerprint,
  GitCommitHorizontal, Image as ImageIcon, Layers, ListChecks, Plus, RefreshCcw, ScanLine, Search, ShieldAlert, ShieldCheck, ShieldQuestion, SquareDashed,
  Timer, UserCheck, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CompareSlider } from "../components/CompareSlider";
import { DropZone } from "../components/DropZone";
import { PhotoViewer, type ViewerAnchor, type ViewerItem } from "../components/PhotoViewer";
import { ProofCard } from "../components/ProofCard";
import { Running } from "../components/Running";
import { Kpi, Marker, Seg, StatusBadge, useToast } from "../components/ui";
import { STATIC, api, dl, followJob, url, useCanLive } from "../lib/api";
import { inspectorName, reviewSummary } from "../lib/reviews";
import { recheckOptions } from "../lib/static";
import { CHECK_TITLE, STATUS_COLOR, isIssue, plural, runDate, statusOf } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { go } from "../lib/router";
import type { Item, JobView, Pt, Result, Review, RunMeta, RunPayload } from "../lib/types";

const R = 4; // rectified px per mm (matches inspector.R)
const mmQuad = (b: number[]): Pt[] => [[b[0] * R, b[1] * R], [(b[0] + b[2]) * R, b[1] * R], [(b[0] + b[2]) * R, (b[1] + b[3]) * R], [b[0] * R, (b[1] + b[3]) * R]];

function VerdictBanner({ p }: { p: RunPayload }) {
  const v = p.meta.verdict;
  const Icon = v.label === "PASS" ? ShieldCheck : v.label === "REVIEW" ? ShieldQuestion : ShieldAlert;
  const c = v.label === "PASS" ? "var(--pass)" : v.label === "REVIEW" ? "var(--review)" : "var(--fail)";
  const rc = p.meta.recheck;
  const real = p.engine_kind === "real";
  const cov = p.coverage;
  const sha = p.meta.photo_meta?.sha256 ?? p.photo_meta?.sha256;
  return (
    <motion.div className="verdict card" style={{ ["--c" as string]: c }} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
      <div className="verdict-main">
        <motion.div className="verdict-icon" initial={{ scale: 0.6, rotate: -12 }} animate={{ scale: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 260, damping: 16, delay: 0.1 }}>
          <Icon />
        </motion.div>
        <div className="grow">
          <div className="verdict-label mono">{v.label === "HOLD" ? "HOLD · DO NOT SHIP" : v.label === "PASS"
            ? (real && cov && cov.verified < cov.total ? "EVERYTHING IN VIEW VERIFIED · PHOTOGRAPH THE REST" : "READY TO SHIP") : "NEEDS A RE-PHOTO"}</div>
          <h2 className="verdict-head">{v.headline.split(" · ")[1] ?? v.headline}</h2>
          <p className="verdict-detail">{v.detail}</p>
          <div className="verdict-meta">
            {p.meta.origin === "cloud" && <span style={{ color: "var(--accent)" }}><Cloud size={13} /> Live cloud engine</span>}
            {p.meta.origin === "recorded" && <span><Cloud size={13} /> Recorded engine run</span>}
            <span><Timer size={13} /> {p.timing.total.toFixed(1)} s on CPU{p.meta.cached ? " · answered from stored metadata" : ""}</span>
            {real ? (
              <>
                <span><Eye size={13} /> {cov ? `${cov.verified}/${cov.total} labelled drawing items verified` : "coverage n/a"} · views {(p.views ?? []).join(", ") || "none"}</span>
                <span style={{ color: p.agent?.enabled ? "var(--accent)" : undefined }}><Bot size={13} /> {p.agent?.enabled ? `Claude verifier · ${p.agent.calls} calls` : "Claude verifier off"}</span>
              </>
            ) : (
              <>
                <span><Crosshair size={13} /> {p.registration.anchors}/{p.registration.targets} anchors · {p.registration.inliers} inliers</span>
                <span><ListChecks size={13} /> {p.meta.items} items from the drawing</span>
              </>
            )}
            {sha && <span title={`SHA-256 ${sha}. The photo itself is not stored: only this fingerprint, its size and the results.`}><Fingerprint size={13} /> photo kept as metadata · {sha.slice(0, 10)}…</span>}
            {(() => {
              const r = reviewSummary(p.meta, p.results);
              return r.decided > 0 ? <span style={{ color: "var(--accent-3)" }}><UserCheck size={13} /> Inspector: {r.confirmed} confirmed · {r.overridden} overridden{r.pending ? ` · ${r.pending} pending` : ""}</span> : null;
            })()}
          </div>
        </div>
      </div>
      <div className="verdict-kpis">
        {rc ? (
          <>
            <Kpi value={rc.CLOSED} label="Closed" color="var(--closed)" note="fixed" />
            <Kpi value={rc.OPEN} label="Open" color="var(--open)" note="still failing" />
            <Kpi value={rc.REGRESSION} label="Regression" color="var(--regression)" note="newly broken" />
            <Kpi value={rc.NEW} label="New" color="var(--new)" note="newly revealed" />
          </>
        ) : (
          <>
            <Kpi value={p.meta.counts.PASS} label="Pass" color="var(--pass)" note="verified" />
            <Kpi value={p.meta.counts.FAIL} label="Fail" color="var(--fail)" note="fix before shipping" />
            <Kpi value={p.meta.counts.REVIEW} label="Review" color="var(--review)" note="re-photo zone" />
            {real ? <Kpi value={p.meta.counts.NOT_IN_VIEW ?? 0} label="Not in view" color="var(--niv)" note="not judged here" />
              : <Kpi value={p.meta.counts.SKIP} label="Skip" color="var(--skip)" note="root cause elsewhere" />}
          </>
        )}
      </div>
    </motion.div>
  );
}

function Chain({ chain, current }: { chain: RunMeta[]; current: string }) {
  if (chain.length < 2) return null;
  return (
    <div className="chain">
      {chain.map((m, i) => (
        <div key={m.id} className="row" style={{ ["--gap" as string]: "6px" }}>
          {i > 0 && <ChevronRight size={14} className="faint" />}
          <a href={`#/run/${m.id}`} className={`chain-pill${m.id === current ? " on" : ""}`} style={{ ["--c" as string]: STATUS_COLOR[m.verdict.label] }}>
            <b>v{m.version}</b>
            <span>{m.verdict.label}{m.counts.FAIL ? ` · ${m.counts.FAIL}` : ""}</span>
          </a>
        </div>
      ))}
    </div>
  );
}

function IssueList({ items, selected, hovered, onSelect, onHover }: {
  items: Item[]; selected: string | null; hovered: string | null; onSelect: (id: string) => void; onHover: (id: string | null) => void;
}) {
  if (!items.length)
    return (
      <div className="empty">
        <ShieldCheck style={{ color: "var(--pass)", opacity: 1 }} />
        <div className="muted">No issues. Every item the drawing expects was verified.</div>
      </div>
    );
  return (
    <div className="issues">
      {items.map((it, i) => {
        const s = statusOf(it);
        return (
          <motion.button key={it.id} className={`issue-card${selected === it.id ? " on" : ""}${hovered === it.id ? " hover" : ""}`}
            style={{ ["--c" as string]: STATUS_COLOR[s] }} onClick={() => onSelect(it.id)} onMouseEnter={() => onHover(it.id)} onMouseLeave={() => onHover(null)}
            initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.15 + i * 0.05 }}>
            <Marker n={it.marker ?? "·"} s={s} />
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="row between">
                <span className="mono issue-id">{it.id}</span>
                <StatusBadge s={s} />
              </div>
              <div className="issue-found ellipsis">{it.found}</div>
              <div className="tiny faint">{CHECK_TITLE[it.check]} · expected <span className="mono">{it.expected}</span></div>
            </div>
          </motion.button>
        );
      })}
    </div>
  );
}

function Checklist({ items, selected, onSelect }: { items: Item[]; selected: string | null; onSelect: (id: string) => void }) {
  const [f, setF] = useState<"ALL" | Result>("ALL");
  const [q, setQ] = useState("");
  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: items.length, PASS: 0, FAIL: 0, REVIEW: 0, SKIP: 0, NOT_IN_VIEW: 0 };
    items.forEach((i) => c[i.result]++);
    return c;
  }, [items]);
  const rows = items.filter((i) => (f === "ALL" || i.result === f) && (!q || `${i.id} ${i.expected} ${i.found}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="checklist">
      <div className="row wrap" style={{ ["--gap" as string]: "6px", marginBottom: 10 }}>
        {(["ALL", "FAIL", "REVIEW", "SKIP", "PASS", "NOT_IN_VIEW"] as const).filter((k) => k !== "NOT_IN_VIEW" || counts[k] > 0).map((k) => (
          <button key={k} className="chip" aria-pressed={f === k} style={{ ["--c" as string]: k === "ALL" ? "var(--accent)" : STATUS_COLOR[k] }} onClick={() => setF(k)}>
            {k === "ALL" ? "All" : k === "NOT_IN_VIEW" ? "Not in view" : k} <span className="count">{counts[k]}</span>
          </button>
        ))}
      </div>
      <div className="input-icon" style={{ marginBottom: 10 }}>
        <Search />
        <input className="input" placeholder="Search item, tag, text…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th>Item</th><th>Expected</th><th>Found</th><th>Result</th></tr>
          </thead>
          <tbody>
            {rows.map((it) => (
              <tr key={it.id} aria-selected={selected === it.id} onClick={() => onSelect(it.id)}>
                <td className="mono nowrap">{it.id}</td>
                <td className="mono small muted">{it.expected}</td>
                <td className="small" style={{ color: it.result === "PASS" ? "var(--text-2)" : STATUS_COLOR[it.result] }}>{it.found}</td>
                <td>
                  <div className="row" style={{ ["--gap" as string]: "5px" }}>
                    <StatusBadge s={it.result} />
                    {it.recheck && <StatusBadge s={it.recheck} />}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="empty small">No items match.</div>}
      </div>
    </div>
  );
}

function Registration({ p }: { p: RunPayload }) {
  const r = p.registration;
  const pts = [...r.anchor_points].sort((a, b) => Number(a.inlier !== false) - Number(b.inlier !== false) || b.residual_mm - a.residual_mm);
  return (
    <div className="stack" style={{ ["--gap" as string]: "14px" }}>
      <div className="reg-stats">
        <div><b>{r.anchors}</b><span>anchors read of {r.targets}</span></div>
        <div><b>{r.inliers}</b><span>RANSAC inliers</span></div>
        <div><b style={{ color: r.outliers.length ? "var(--fail)" : undefined }}>{r.outliers.length}</b><span>off-pattern</span></div>
      </div>
      {p.engine_kind === "real" ? (
        <p className="small muted">
          Every device label read with certainty is an anchor; per GA view a 2-point RANSAC finds the placement of the drawing on the photo
          ({r.refined ? "refined to a homography" : "similarity transform"}). Only drawing items inside the covered area are judged; the rest are NOT IN VIEW.
          {r.outliers.length > 0 && <> Labels that don't fit the drawing point to misplaced parts: <b className="mono">{r.outliers.join(", ")}</b>.</>}
        </p>
      ) : (
        <p className="small muted">
          The backplate outline gives a coarse fit; every label and ferrule EAGLE EYE can read with certainty then becomes an anchor, and a RANSAC
          homography refines the fit ({r.refined ? "refinement accepted" : "coarse fit kept"}).
          {r.outliers.length > 0 && <> Anchors that don't fit the drawing point to misplaced parts: <b className="mono">{r.outliers.join(", ")}</b>.</>}
        </p>
      )}
      <div className="table-wrap" style={{ maxHeight: 300 }}>
        <table className="table">
          <thead><tr><th>Anchor</th><th>Kind</th><th>Residual</th><th>Fit</th></tr></thead>
          <tbody>
            {pts.map((a) => (
              <tr key={a.tag + a.found_px.join()} style={{ cursor: "default" }}>
                <td className="mono small">{a.tag}</td>
                <td className="tiny faint">{a.kind}</td>
                <td className="mono small">{a.residual_mm.toFixed(1)} {p.engine_kind === "real" ? "pt" : "mm"}</td>
                <td>{a.inlier === false ? <StatusBadge s="FAIL" label="OUTLIER" /> : <StatusBadge s="PASS" label="INLIER" />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TimingCard({ p }: { p: RunPayload }) {
  const t = p.timing;
  const parts = [
    { k: "Parse drawing", v: t.parse, c: "#818cf8" },
    ...(t.ocr != null ? [{ k: "Read labels (OCR)", v: t.ocr, c: "#f472b6" }] : []),
    { k: "Register photo", v: t.register, c: "#38bdf8" },
    ...Object.entries(t.checks).map(([k, v]) => ({ k: `${k} check`, v, c: "#22d3ee" })),
    ...(t.agent ? [{ k: "Claude verifier", v: t.agent, c: "#fbbf24" }] : []),
    { k: "Report + PDF", v: p.meta.timing.report ?? 0, c: "#a78bfa" },
  ];
  const total = parts.reduce((a, b) => a + b.v, 0) || 1;
  return (
    <div className="card pad">
      <div className="card-head">
        <div className="card-title"><Timer /> Where the {total.toFixed(1)} s went</div>
        <span className="tiny faint">OCR runs in parallel on every core</span>
      </div>
      <div className="tbar">
        {parts.map((x) => <i key={x.k} style={{ width: `${(x.v / total) * 100}%`, background: x.c }} title={`${x.k}: ${x.v.toFixed(2)} s`} />)}
      </div>
      <div className="tlegend">
        {parts.map((x) => (
          <span key={x.k}><i style={{ background: x.c }} />{x.k} <b className="mono">{x.v.toFixed(2)}s</b></span>
        ))}
      </div>
    </div>
  );
}

/** Human in the loop: the inspector confirms or overrides the engine on one item. Kept as an audit trail. */
function DecisionBar({ it, review, onDecide }: { it: Item; review?: Review; onDecide: (item: string, d: Review["decision"] | "CLEAR", note: string) => void }) {
  const [note, setNote] = useState(review?.note ?? "");
  if (it.result === "SKIP") return null;
  const engine = it.result;
  return (
    <div className={`decision${review ? " done" : ""}`} style={{ ["--c" as string]: review ? STATUS_COLOR[review.decision] : "var(--accent-3)" }}>
      <div className="row between wrap" style={{ ["--gap" as string]: "8px" }}>
        <div className="tiny faint row" style={{ ["--gap" as string]: "6px" }}><UserCheck size={13} /> Inspector decision</div>
        {review && (
          <span className="tiny">
            <b style={{ color: STATUS_COLOR[review.decision] }}>{review.decision === engine ? "Confirmed" : "Overridden"} {review.decision}</b>
            <span className="faint"> · {review.by} · {runDate(review.at)}</span>
          </span>
        )}
      </div>
      <div className="row" style={{ ["--gap" as string]: "6px" }}>
        <input className="input grow" placeholder={engine === "REVIEW" ? "What did you see on the cabinet?" : "Note (optional)"} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
        <button className="btn btn-sm" style={{ ["--c" as string]: "var(--pass)" }} onClick={() => onDecide(it.id, "PASS", note)} title="The item is correct on the cabinet">
          <CheckCircle2 style={{ color: "var(--pass)" }} /> PASS
        </button>
        <button className="btn btn-sm" onClick={() => onDecide(it.id, "FAIL", note)} title="The item is wrong on the cabinet">
          <XCircle style={{ color: "var(--fail)" }} /> FAIL
        </button>
        {review && <button className="btn btn-sm btn-ghost" onClick={() => { setNote(""); onDecide(it.id, "CLEAR", ""); }}>Undo</button>}
      </div>
    </div>
  );
}

function RecheckCard({ p, onStart }: { p: RunPayload; onStart: (photo: File | null, sample: string | null) => void }) {
  const [photo, setPhoto] = useState<File | null>(null);
  const samples = useAsync(api.samples);
  const live = useCanLive();
  const real = p.engine_kind === "real";
  const suggested = !real && p.meta.photo_name.startsWith("01_") && !p.meta.parent ? "05" : null;
  const recorded = STATIC && !live ? recheckOptions(p.meta.id) : null;
  return (
    <div className="card pad recheck">
      <div className="card-head">
        <div>
          <div className="card-title"><RefreshCcw /> Technician fixed it? Re-check.</div>
          <div className="card-sub">Upload the new photo. Fixed items CLOSE, the rest stay OPEN, anything newly broken is a REGRESSION, and the history is kept.</div>
        </div>
      </div>
      <div className="recheck-grid">
        {!live ? (
          <div className="card flat pad small muted">
            Replay mode: re-checks recorded from the real engine. Uploading the after-fix photo needs the live engine (switch at the top right).
            {recorded && !recorded.length && <div style={{ marginTop: 8 }}>No re-check was recorded for this run; open <b>Sample 01</b> to try one.</div>}
          </div>
        ) : (
          <DropZone accept=".jpg,.jpeg,.png" file={photo} onFile={setPhoto} preview title="Drop the photo taken after the fix" hint="Same cabinet, any angle" icon={<Camera />} />
        )}
        <div className="stack" style={{ ["--gap" as string]: "8px" }}>
          {real ? <div className="tiny faint">Re-photograph the same side of the cabinet after the fix; the drawing set of this run is reused.</div> : <>
          <div className="tiny faint">…or re-check with a sample photo</div>
          <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
            {samples.data?.filter((s) => !recorded || recorded.includes(s.id)).map((s) => (
              <button key={s.id} className="chip" aria-pressed={s.id === suggested} onClick={() => onStart(null, s.id)} title={s.subtitle}>
                {s.id} · {s.title}
              </button>
            ))}
          </div>
          {suggested && <div className="tiny muted">Suggested: <b>05 · After the fix</b>, a re-photo of sample 01 with one fault left.</div>}
          </>}
          {live && (
            <button className="btn btn-primary btn-lg" disabled={!photo} onClick={() => onStart(photo, null)} style={{ marginTop: "auto" }}>
              <RefreshCcw /> Re-check with uploaded photo
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function Run({ id }: { id: string }) {
  const toast = useToast();
  const { data: p, error, setData } = useAsync(() => api.run(id), [id]);
  const chain = useAsync(() => api.chain(id), [id]);
  const [mode, setMode] = useState<"photo" | "rect">("photo");
  const [layers, setLayers] = useState({ issues: true, drawing: false, anchors: false });
  const [opacity, setOpacity] = useState(0.7);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState(0);
  const pick = (id: string) => { setSelected(id); setFocusKey((k) => k + 1); };
  const [hovered, setHovered] = useState<string | null>(null);
  const [tab, setTab] = useState<"issues" | "checklist" | "registration">("issues");
  const [job, setJob] = useState<JobView | null>(null);
  const [jobPhoto, setJobPhoto] = useState<string>("");

  const issues = useMemo(() => (p ? p.results.filter(isIssue).sort((a, b) => (a.marker ?? 0) - (b.marker ?? 0)) : []), [p]);
  useEffect(() => {
    setSelected(null);
    setFocusKey(0);
    setMode("photo");
  }, [id]);
  useEffect(() => {
    if (p && p.meta.id === id && !selected) setSelected((issues[0] ?? p.results[0]).id);
  }, [p, id, issues, selected]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!issues.length || (e.target as HTMLElement).tagName === "INPUT") return;
      const i = issues.findIndex((x) => x.id === selected);
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); pick(issues[(i + 1) % issues.length].id); }
      if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); pick(issues[(i - 1 + issues.length) % issues.length].id); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [issues, selected]);

  const startRecheck = async (photo: File | null, sample: string | null) => {
    setJobPhoto(photo ? URL.createObjectURL(photo) : url.sample(sample!, 1400));
    try {
      const j = await api.inspect({ photo, sample, parent: id, checks: p?.meta.enabled });
      setJob(j);
      const done = await followJob(j.id, setJob);
      if (done.status === "error") throw new Error(done.error ?? "Re-check failed");
      if (done.note) toast("ok", done.note);
      setJob(null);
      go(`run/${done.run_id}`);
    } catch (e) {
      toast("error", (e as Error).message);
      setJob(null);
    }
  };

  const decide = async (item: string, decision: Review["decision"] | "CLEAR", note: string) => {
    if (!p) return;
    try {
      const m = await api.review(id, item, decision, note, inspectorName());
      setData({ ...p, meta: { ...p.meta, reviews: m.reviews ?? {} } });
      toast("ok", decision === "CLEAR" ? `Decision on ${item} cleared` : `${item}: ${decision} recorded by ${inspectorName()}`);
    } catch (e) {
      toast("error", (e as Error).message);
    }
  };

  if (error) return <div className="main"><div className="card pad empty">Could not load run: {error}<button className="btn" onClick={() => go("history")}>Open history</button></div></div>;
  if (!p || p.meta.id !== id) return <div className="main"><div className="skeleton" style={{ height: 160, marginBottom: 18 }} /><div className="skeleton" style={{ height: 700 }} /></div>;
  if (job) return <div className="main"><Running job={job} photo={jobPhoto} enabled={p.meta.enabled} title={`Re-check of ${p.meta.label}`} /></div>;

  const sel = p.results.find((r) => r.id === selected) ?? null;
  const rect = mode === "rect";
  const space: [number, number] = rect ? [p.size_mm[0] * R, p.size_mm[1] * R] : p.photo_size;
  const vItems: ViewerItem[] = issues.map((it) => ({ id: it.id, quad: rect ? mmQuad(it.box) : it.quad, status: statusOf(it), marker: it.marker, caption: `${it.id} · ${it.found}` }));
  const vLayout = p.layout.map((l) => ({ tag: l.tag, kind: l.kind, quad: rect ? mmQuad(l.box) : l.quad }));
  const vAnchors: ViewerAnchor[] = p.registration.anchor_points.map((a) => ({
    tag: a.tag, inlier: a.inlier,
    found: rect ? [a.found_mm[0] * R, a.found_mm[1] * R] : a.found_px,
    expected: rect ? [a.expected_mm[0] * R, a.expected_mm[1] * R] : a.expected_px,
  }));
  const selQuad = sel ? (rect ? mmQuad(sel.box) : sel.quad) : null;
  const parent = chain.data?.find((m) => m.id === p.meta.parent);

  return (
    <div className="main run">
      <div className="run-head">
        <div className="stack" style={{ ["--gap" as string]: "8px" }}>
          <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
            <button className="btn btn-sm btn-ghost" onClick={() => go("inspect")}><ArrowLeft /> Inspect</button>
            <span className="faint">/</span>
            <span className="tag accent">{p.meta.cabinet}</span>
            <span className="small muted">{p.meta.label}</span>
            <span className="tiny faint">· {runDate(p.meta.created)} · run {p.meta.id}</span>
          </div>
          {chain.data && <Chain chain={chain.data} current={id} />}
        </div>
        <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
          <a className="btn" {...dl(id, "pdf", p.meta.cabinet)}><FileText /> PDF report</a>
          <a className="btn" {...dl(id, "checklist", p.meta.cabinet)}><FileSpreadsheet /> Filled checklist</a>
          <a className="btn btn-icon" {...dl(id, "json", p.meta.cabinet)} title="Report JSON"><FileJson /></a>
          <a className="btn btn-icon" {...dl(id, "marked", p.meta.cabinet)} title="Marked-up photo"><Download /></a>
          <a className="btn" href={`#/work/${id}`} title="Printable fix list for the technician"><ClipboardList /> Work order</a>
          <button className="btn btn-primary" onClick={() => document.getElementById("recheck")?.scrollIntoView({ behavior: "smooth", block: "center" })}><RefreshCcw /> Re-check</button>
          <button className="btn btn-icon" onClick={() => go("inspect")} title="New inspection"><Plus /></button>
        </div>
      </div>

      <VerdictBanner p={p} />
      {(p.meta.warnings ?? []).map((w) => (
        <div key={w.code} className={`callout ${w.code === "weak_registration" ? "warn" : "info"}`}>
          {w.code === "weak_registration" ? <ShieldQuestion /> : <RefreshCcw />}
          <span>{w.message}</span>
        </div>
      ))}

      <div className="workbench">
        <div className="card viewer-card">
          <div className="viewer-toolbar">
            <Seg value={mode} onChange={setMode} options={[
              { value: "photo", label: <><ImageIcon /> Photo</>, title: "The photo as taken, with every issue boxed" },
              ...(p.rectified === false ? [] : [{ value: "rect" as const, label: <><SquareDashed /> Aligned to drawing</>, title: "Photo warped onto the GA drawing" }]),
            ]} />
            <div className="row" style={{ ["--gap" as string]: "6px" }}>
              <button className="chip" aria-pressed={layers.issues} onClick={() => setLayers({ ...layers, issues: !layers.issues })}><ScanLine /> Issues</button>
              <button className="chip" aria-pressed={layers.drawing} onClick={() => setLayers({ ...layers, drawing: !layers.drawing })}><Layers /> Drawing</button>
              <button className="chip" aria-pressed={layers.anchors} onClick={() => setLayers({ ...layers, anchors: !layers.anchors })}><Crosshair /> Anchors</button>
            </div>
            {rect && (
              <div className="row opacity-ctl" style={{ ["--gap" as string]: "8px" }}>
                <span className="tiny faint nowrap">GA overlay</span>
                <input className="range" type="range" min={0} max={1} step={0.01} value={opacity} onChange={(e) => setOpacity(+e.target.value)} style={{ ["--p" as string]: `${opacity * 100}%`, width: 110 }} />
              </div>
            )}
          </div>
          <PhotoViewer
            key={mode}
            height="max(520px, calc(100vh - var(--nav-h) - 132px))"
            src={rect ? url.file(id, "rectified") : url.file(id, "photo")}
            size={space}
            items={vItems}
            layout={vLayout}
            anchors={vAnchors}
            backplate={rect ? [[0, 0], [space[0], 0], [space[0], space[1]], [0, space[1]]] : p.backplate_quad}
            layers={layers}
            overlaySrc={rect ? url.file(id, "overlay") : undefined}
            overlayOpacity={opacity}
            selected={selected}
            selectedQuad={selQuad}
            hovered={hovered}
            focusKey={focusKey}
            onSelect={setSelected}
            onHover={setHovered}
          />
          <div className="viewer-foot tiny faint">
            Scroll to zoom · drag to pan · double-click to fit · <kbd>↑</kbd> <kbd>↓</kbd> step through issues
          </div>
        </div>

        <div className="side">
          <div className="card pad">
            {sel ? <ProofCard run={id} it={sel} geo={{ photoSize: p.photo_size, sizeMm: p.size_mm, real: p.engine_kind === "real" }} /> : <div className="empty">Select an item</div>}
            {sel && <DecisionBar key={sel.id} it={sel} review={p.meta.reviews?.[sel.id]} onDecide={decide} />}
          </div>
          <div className="card side-tabs">
            <div className="tabs">
              {([
                ["issues", `Issues`, issues.length],
                ["checklist", "Checklist", p.results.length],
                ["registration", "Registration", p.registration.anchors],
              ] as const).map(([k, l, n]) => (
                <button key={k} className={`tab${tab === k ? " on" : ""}`} onClick={() => setTab(k)}>
                  {l} <span className="mono">{n}</span>
                  {tab === k && <motion.i layoutId="tab-u" className="tab-u" />}
                </button>
              ))}
            </div>
            <div className="tab-body">
              <AnimatePresence mode="wait">
                <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
                  {tab === "issues" && <IssueList items={issues} selected={selected} hovered={hovered} onSelect={pick} onHover={setHovered} />}
                  {tab === "checklist" && <Checklist items={p.results} selected={selected} onSelect={pick} />}
                  {tab === "registration" && <Registration p={p} />}
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>

      {parent && (
        <div className="card pad compare-card">
          <div className="card-head">
            <div>
              <div className="card-title"><GitCommitHorizontal /> Before and after the fix</div>
              <div className="card-sub">Drag the handle. Left: v{parent.version} ({parent.verdict.label}). Right: v{p.meta.version} ({p.meta.verdict.label}).</div>
            </div>
            <a className="btn btn-sm" href={`#/run/${parent.id}`}>Open v{parent.version}</a>
          </div>
          <div className="compare-wrap">
            <CompareSlider before={url.file(parent.id, "marked", 1400)} after={url.file(id, "marked", 1400)} labelBefore={`v${parent.version} · ${plural(parent.counts.FAIL, "FAIL", "FAIL")}`} labelAfter={`v${p.meta.version} · ${p.meta.recheck?.CLOSED ?? 0} CLOSED · ${p.meta.recheck?.OPEN ?? 0} OPEN`} aspect={p.photo_size[0] / p.photo_size[1]} />
            <div className="stack" style={{ ["--gap" as string]: "8px" }}>
              {issues.map((it) => (
                <button key={it.id} className="rc-row" onClick={() => { pick(it.id); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                  <Marker n={it.marker ?? "·"} s={statusOf(it)} />
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div className="mono small">{it.id}</div>
                    <div className="tiny faint ellipsis">{it.prev_result ? `${it.prev_result}: ${it.prev_found} → ` : ""}{it.result}: {it.found}</div>
                  </div>
                  <StatusBadge s={statusOf(it)} />
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="run-bottom">
        <div id="recheck"><RecheckCard p={p} onStart={startRecheck} /></div>
        <TimingCard p={p} />
      </div>
    </div>
  );
}
