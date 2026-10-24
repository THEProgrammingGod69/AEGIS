import { motion } from "framer-motion";
import { BarChart3, Clock4, Flame, ShieldAlert, ShieldCheck, ShieldQuestion, Table2, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FaultPareto } from "../components/FaultPareto";
import { Kpi, Seg, StatusBadge } from "../components/ui";
import { api, url } from "../lib/api";
import type { ParetoBy } from "../lib/assembly";
import { CHECK_TITLE, STATUS_COLOR, runDate } from "../lib/format";
import { useAsync, useSize } from "../lib/hooks";
import { go } from "../lib/router";
import type { RunMeta, RunPayload } from "../lib/types";

type Scope = "all" | "inspect" | "forge";

const CHECK_OF: Record<string, string> = { GA: "GA", ORD: "ORDER", LBL: "LABEL", FER: "FERRULE", COL: "COLOUR" };
const checkOf = (id: string) => CHECK_OF[id.split("-")[0]] ?? id.split("-")[0];
const VERDICT_ICON = { PASS: ShieldCheck, HOLD: ShieldAlert, REVIEW: ShieldQuestion } as const;
const VERDICT_TEXT = { PASS: "Ready to ship", HOLD: "Hold: faults to fix", REVIEW: "Needs a re-photo" } as const;
const R = 4; // rectified px per mm

/** Fault frequency drawn on the cabinet itself: one bubble per drawing item, area ∝ how often it failed. */
function Heatmap({ base, heat, scope, focus }: { base: RunPayload; heat: Map<string, { n: number; runs: number }>; scope: string; focus?: Set<string> | null }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hover, setHover] = useState<string | null>(null);
  const W = base.size_mm[0] * R;
  const H = base.size_mm[1] * R;
  const max = Math.max(1, ...[...heat.values()].map((v) => v.n));
  const k = size.w ? size.w / W : 0;
  const items = base.results.filter((r) => heat.has(r.id));
  const hot = hover ? items.find((r) => r.id === hover) : null;
  return (
    <div className="heat" ref={ref} style={{ aspectRatio: `${W} / ${H}` }}>
      <img src={url.file(base.meta.id, "rectified")} alt="Cabinet backplate, aligned to the drawing" />
      <div className="heat-dim" />
      {k > 0 && (
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Fault locations on the cabinet (${scope})`}>
          {base.layout.map((l) => (
            <rect key={l.tag} x={l.box[0] * R} y={l.box[1] * R} width={l.box[2] * R} height={l.box[3] * R} className="heat-box" />
          ))}
          {items.map((r) => {
            const v = heat.get(r.id)!;
            const cx = (r.box[0] + r.box[2] / 2) * R;
            const cy = (r.box[1] + r.box[3] / 2) * R;
            const rad = 22 + 70 * Math.sqrt(v.n / max);
            return (
              <g key={r.id} className={`heat-spot${hover === r.id ? " on" : ""}${focus && !focus.has(r.id) ? " dim" : ""}`} onMouseEnter={() => setHover(r.id)} onMouseLeave={() => setHover(null)}>
                <circle cx={cx} cy={cy} r={rad + 24} fill="transparent" />
                <circle cx={cx} cy={cy} r={rad} className="heat-glow" style={{ opacity: 0.25 + 0.55 * (v.n / max) }} />
                <circle cx={cx} cy={cy} r={Math.max(14, rad * 0.42)} className="heat-core" />
                <text x={cx} y={cy + 9} textAnchor="middle" className="heat-n">{v.n}</text>
              </g>
            );
          })}
        </svg>
      )}
      {hot && (
        <div className="heat-tip" style={{ left: `${((hot.box[0] + hot.box[2] / 2) / base.size_mm[0]) * 100}%`, top: `${(hot.box[1] / base.size_mm[1]) * 100}%` }}>
          <b className="mono">{hot.id}</b>
          <span>{CHECK_TITLE[hot.check] ?? hot.check} · {hot.target}</span>
          <span>{heat.get(hot.id)!.n} FAIL in {heat.get(hot.id)!.runs} run(s)</span>
        </div>
      )}
      {!items.length && <div className="heat-empty">No faults in this selection.</div>}
    </div>
  );
}

export function Analytics() {
  const runs = useAsync(() => api.runs(500));
  const live = useAsync(api.forgeLive);
  const [scope, setScope] = useState<Scope>("all");
  const [manual, setManual] = useState(25);
  const [table, setTable] = useState(false);
  const [base, setBase] = useState<RunPayload | null>(null);
  const [by, setBy] = useState<ParetoBy>("fault");
  const [focus, setFocus] = useState<{ key: string; ids: Set<string> } | null>(null);

  const metas = useMemo(() => (runs.data ?? []).filter((m) => scope === "all" || (scope === "forge" ? m.source === "forge" : m.source !== "forge")), [runs.data, scope]);
  const chrono = useMemo(() => [...metas].sort((a, b) => a.created.localeCompare(b.created) || a.id.localeCompare(b.id)), [metas]);

  // a non-forge run gives the backdrop for the heatmap (same demo drawing for every run)
  useEffect(() => {
    const pick = (runs.data ?? []).find((m) => m.source !== "forge" && m.inputs.ga.demo) ?? runs.data?.[0];
    if (pick && base?.meta.id !== pick.id) api.run(pick.id).then(setBase).catch(() => {});
  }, [runs.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const s = useMemo(() => {
    const first = metas.filter((m) => m.version === 1);
    const fpy = first.length ? first.filter((m) => m.verdict.label === "PASS").length / first.length : 0;
    const fails = metas.reduce((a, m) => a + m.counts.FAIL, 0);
    const items = metas.reduce((a, m) => a + m.items, 0);
    const reviews = metas.reduce((a, m) => a + m.counts.REVIEW, 0);
    const rc = metas.filter((m) => m.recheck);
    const closed = rc.reduce((a, m) => a + (m.recheck?.CLOSED ?? 0), 0);
    const open = rc.reduce((a, m) => a + (m.recheck?.OPEN ?? 0), 0);
    const secs = metas.map((m) => m.timing.total).filter((x) => x > 0);
    const avg = secs.length ? secs.reduce((a, b) => a + b, 0) / secs.length : 0;
    // agreement is measured where the engine took a position (FAIL); REVIEW items are the engine asking a person
    const decided = metas.flatMap((m) => Object.entries(m.reviews ?? {}).map(([id, r]) => ({ m, id, r, eng: m.issues.find((i) => i.id === id)?.result })))
      .filter((x) => x.eng === "FAIL");
    const agree = decided.filter(({ r }) => r.decision === "FAIL").length;
    const byCheck: Record<string, number> = { GA: 0, ORDER: 0, LABEL: 0, FERRULE: 0, COLOUR: 0 };
    const heat = new Map<string, { n: number; runs: number }>();
    const last = new Map<string, RunMeta>();
    for (const m of metas)
      for (const i of m.issues) {
        if (i.result !== "FAIL") continue;
        byCheck[checkOf(i.id)] = (byCheck[checkOf(i.id)] ?? 0) + 1;
        const h = heat.get(i.id) ?? { n: 0, runs: 0 };
        heat.set(i.id, { n: h.n + 1, runs: h.runs + 1 });
        if (!last.has(i.id) || last.get(i.id)!.created < m.created) last.set(i.id, m);
      }
    const verdicts = { PASS: 0, HOLD: 0, REVIEW: 0 };
    metas.forEach((m) => verdicts[m.verdict.label]++);
    return { first, fpy, fails, items, reviews, closed, open, avg, decided, agree, byCheck, heat, last, verdicts };
  }, [metas]);

  const n = metas.length;
  const savedH = Math.max(0, (n * (manual * 60 - s.avg)) / 3600);
  const maxCheck = Math.max(1, ...Object.values(s.byCheck));
  const maxFail = Math.max(1, ...chrono.map((m) => m.counts.FAIL));
  const L = live.data;

  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">QC analytics</span>
          <h1>What the line keeps getting wrong.</h1>
          <p>Every inspection, re-check and inspector decision {n ? `in this ${runs.data && runs.data.length === n ? "history" : "selection"}` : ""}, rolled up: first-pass yield, where faults cluster on the cabinet, how fast fixes close, and how often a person agreed with the engine.</p>
        </div>
        <Seg value={scope} onChange={setScope} options={[{ value: "all", label: "All runs" }, { value: "inspect", label: "Inspections" }, { value: "forge", label: "Fault Forge" }]} />
      </div>

      {runs.data && !n && (
        <div className="card pad empty"><BarChart3 /><div className="muted">No runs in this selection yet.</div><button className="btn btn-primary" onClick={() => go("inspect")}>Run an inspection</button></div>
      )}

      {n > 0 && (
        <>
          <div className="an-kpis">
            <Kpi value={n} label="cabinets inspected" color="var(--accent)" note={`${s.items.toLocaleString()} items checked`} />
            <Kpi value={s.fpy * 100} suffix="%" label="first-pass yield" color="var(--pass)" note={`${s.first.filter((m) => m.verdict.label === "PASS").length} of ${s.first.length} first inspections`} />
            <Kpi value={s.fails} label="faults caught" color="var(--fail)" note="each with expected-vs-found proof" />
            <Kpi value={s.closed + s.open ? (s.closed / (s.closed + s.open)) * 100 : 0} suffix="%" label="fix closure" color="var(--closed)" note={`${s.closed} closed · ${s.open} open on re-check`} />
            <Kpi value={s.avg} decimals={1} suffix="s" label="per cabinet" color="var(--accent-3)" note="engine time, CPU only" />
            <Kpi value={s.decided.length ? (s.agree / s.decided.length) * 100 : 100} suffix="%" label="inspector agreement" color="var(--accent-2)" note={s.decided.length ? `${s.agree}/${s.decided.length} FAILs confirmed` : "no FAILs reviewed yet"} />
          </div>

          <div className="an-grid">
            <motion.div className="card pad an-heat" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
              <div className="card-head">
                <div>
                  <div className="card-title"><Flame /> Fault heatmap on the cabinet</div>
                  <div className="card-sub">Bubble area = how often that drawing item failed. Hover a bubble for the item{focus ? "; showing the Pareto row picked below" : ""}.</div>
                </div>
              </div>
              {base ? <Heatmap base={base} heat={s.heat} scope={scope} focus={focus?.ids} /> : <div className="skeleton" style={{ aspectRatio: "0.72" }} />}
            </motion.div>

            <div className="stack" style={{ ["--gap" as string]: "18px" }}>
              <motion.div className="card pad" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
                <div className="card-head">
                  <div className="card-title"><BarChart3 /> Faults by check</div>
                  <span className="tiny faint">{s.fails} FAIL</span>
                </div>
                <div className="hbars">
                  {Object.entries(s.byCheck).sort((a, b) => b[1] - a[1]).map(([k, v], i) => (
                    <div key={k} className="hbar-row tip" data-tip={`${CHECK_TITLE[k] ?? k}: ${v} FAIL (${s.fails ? Math.round((v / s.fails) * 100) : 0}%)`}>
                      <span className="small">{CHECK_TITLE[k] ?? k}</span>
                      <div className="hbar-track"><motion.i initial={{ width: 0 }} animate={{ width: `${(v / maxCheck) * 100}%` }} transition={{ duration: 0.8, delay: i * 0.05 }} /></div>
                      <span className="mono small">{v}</span>
                    </div>
                  ))}
                </div>
              </motion.div>

              <motion.div className="card pad" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
                <div className="card-head">
                  <div className="card-title"><ShieldCheck /> Outcomes</div>
                  <span className="tiny faint">{n} runs</span>
                </div>
                <div className="outcome-bar" role="img" aria-label={`PASS ${s.verdicts.PASS}, HOLD ${s.verdicts.HOLD}, REVIEW ${s.verdicts.REVIEW}`}>
                  {(["PASS", "HOLD", "REVIEW"] as const).filter((k) => s.verdicts[k]).map((k) => (
                    <i key={k} className="tip" data-tip={`${VERDICT_TEXT[k]}: ${s.verdicts[k]} (${Math.round((s.verdicts[k] / n) * 100)}%)`} style={{ flexGrow: s.verdicts[k], background: STATUS_COLOR[k] }} />
                  ))}
                </div>
                <div className="outcome-legend">
                  {(["PASS", "HOLD", "REVIEW"] as const).map((k) => {
                    const Icon = VERDICT_ICON[k];
                    return (
                      <span key={k}><Icon size={14} style={{ color: STATUS_COLOR[k] }} /> {VERDICT_TEXT[k]} <b className="mono">{s.verdicts[k]}</b></span>
                    );
                  })}
                </div>
              </motion.div>

              <motion.div className="card pad" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
                <div className="card-head">
                  <div className="card-title"><Clock4 /> Time saved (estimate)</div>
                </div>
                <div className="saved">
                  <div className="saved-n"><b>{savedH.toFixed(1)}</b><span>inspector hours</span></div>
                  <label className="ctl grow">
                    <span className="row between tiny faint">Manual check per cabinet <b className="mono">{manual} min</b></span>
                    <input className="range" type="range" min={5} max={60} step={1} value={manual} onChange={(e) => setManual(+e.target.value)} style={{ ["--p" as string]: `${((manual - 5) / 55) * 100}%` }} />
                  </label>
                </div>
                <div className="tiny faint">{n} cabinets × ({manual} min by hand − {s.avg.toFixed(1)} s with EAGLE EYE). Adjust the manual time to your line.</div>
              </motion.div>
            </div>
          </div>

          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }} style={{ marginTop: 18 }}>
            <FaultPareto metas={metas} base={base} by={by} onBy={setBy} focus={focus?.key ?? null}
              onFocus={(r) => setFocus(r ? { key: r.key, ids: r.ids } : null)} />
          </motion.div>

          <div style={{ marginTop: 18 }}>
            <motion.div className="card pad" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
              <div className="card-head">
                <div>
                  <div className="card-title"><TrendingUp /> Run by run</div>
                  <div className="card-sub">Faults found per inspection, oldest to newest. Colour = verdict.</div>
                </div>
                <button className="btn btn-sm btn-ghost" onClick={() => setTable(!table)} aria-pressed={table}><Table2 /> {table ? "Chart" : "Table"}</button>
              </div>
              {table ? (
                <div className="table-wrap" style={{ maxHeight: 260 }}>
                  <table className="table">
                    <thead><tr><th>Run</th><th>When</th><th>FAIL</th><th>Verdict</th></tr></thead>
                    <tbody>{[...chrono].reverse().map((m) => (
                      <tr key={m.id} onClick={() => go(`run/${m.id}`)}><td className="small">{m.label}</td><td className="tiny faint nowrap">{runDate(m.created)}</td><td className="mono small">{m.counts.FAIL}</td><td><StatusBadge s={m.verdict.label} /></td></tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : (
                <div className="cols" role="img" aria-label="Faults per run over time">
                  <div className="cols-grid"><i /><i /><i /></div>
                  {chrono.map((m) => (
                    <a key={m.id} href={`#/run/${m.id}`} className="col tip" data-tip={`${m.label}\n${runDate(m.created)} · ${m.counts.FAIL} FAIL · ${m.verdict.label}`}>
                      <i style={{ height: `${Math.max(4, (m.counts.FAIL / maxFail) * 100)}%`, background: STATUS_COLOR[m.verdict.label] }} />
                    </a>
                  ))}
                </div>
              )}
              <div className="row between tiny faint" style={{ marginTop: 8 }}><span>{chrono[0] ? runDate(chrono[0].created) : ""}</span><span>max {maxFail} FAIL</span><span>{chrono.length ? runDate(chrono[chrono.length - 1].created) : ""}</span></div>
            </motion.div>

          </div>

          {L && L.cabinets > 0 && (
            <div className="card pad an-forge">
              <div className="card-title"><ShieldCheck /> Engine reliability (Fault Forge, scored against hidden answer keys)</div>
              <div className="an-forge-kpis">
                <Kpi value={L.cabinets} label="unseen cabinets" color="var(--accent)" />
                <Kpi value={L.planted ? (L.caught / L.planted) * 100 : 100} suffix="%" label="recall" color="var(--pass)" note={`${L.caught}/${L.planted} planted faults`} />
                <Kpi value={L.false_alarms} label="false alarms" color={L.false_alarms ? "var(--fail)" : "var(--text-2)"} note={`over ${L.correct_items.toLocaleString()} correct items`} />
                <Kpi value={L.reviews} label="sent to review" color="var(--review)" note="instead of guessing" />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
