import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Dices, Eye, EyeOff, FlaskConical, Gauge, Play, ShieldCheck, Target, Terminal, XCircle } from "lucide-react";
import { useState } from "react";
import { PhotoViewer } from "../components/PhotoViewer";
import { Running } from "../components/Running";
import { Kpi, Reveal, Seg, StatusBadge, useToast } from "../components/ui";
import { STATIC, api, followJob, url } from "../lib/api";
import { STATUS_COLOR, isIssue, statusOf } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { JobView, RunPayload } from "../lib/types";

const TYPE_LABEL: Record<string, string> = {
  missing_component: "Missing part",
  swap_breakers: "Swapped breakers",
  missing_label: "Missing label",
  wrong_label: "Wrong label",
  missing_ferrule: "Missing ferrule",
  wrong_ferrule: "Wrong ferrule",
  wrong_colour: "Wrong wire colour",
};

function strengthLabel(s: number) {
  return s < 0.9 ? "Gentle" : s < 1.1 ? "Typical" : s < 1.3 ? "Rough" : "Brutal";
}

function Result({ p, others }: { p: RunPayload; others: RunPayload["meta"][] }) {
  const [reveal, setReveal] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [fk, setFk] = useState(0);
  const f = p.meta.forge!;
  const sc = f.score;
  const issues = p.results.filter(isIssue);
  const perfect = sc.caught === sc.n_planted && sc.false_alarms.length === 0;
  return (
    <motion.div className="forge-result" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}>
      <div className="card viewer-card">
        <div className="viewer-toolbar">
          <div className="row" style={{ ["--gap" as string]: "8px" }}>
            <span className="tag accent">Seed {f.seed}</span>
            <span className="tag">Camera {f.strength.toFixed(2)} · {strengthLabel(f.strength)}</span>
          </div>
          <a className="btn btn-sm" href={`#/run/${p.meta.id}`}>Open full report</a>
        </div>
        <PhotoViewer src={url.file(p.meta.id, "photo")} size={p.photo_size} height="min(68vh, 720px)"
          items={issues.map((it) => ({ id: it.id, quad: it.quad, status: statusOf(it), marker: it.marker, caption: `${it.id} · ${it.found}` }))}
          selected={sel} onSelect={setSel} focusKey={fk} />
      </div>
      <div className="stack" style={{ ["--gap" as string]: "16px" }}>
        <div className="card pad" style={{ ["--c" as string]: perfect ? "var(--pass)" : "var(--fail)" }}>
          <div className="forge-verdict">
            {perfect ? <ShieldCheck style={{ color: "var(--pass)" }} /> : <XCircle style={{ color: "var(--fail)" }} />}
            <div>
              <div className="mono tiny faint">SCORE AGAINST THE HIDDEN ANSWER KEY</div>
              <h3>{perfect ? (sc.n_planted ? `All ${sc.n_planted} planted faults caught, no false alarms` : "Clean cabinet, zero false alarms") : `${sc.caught}/${sc.n_planted} caught · ${sc.false_alarms.length} false alarm(s)`}</h3>
            </div>
          </div>
          <div className="forge-kpis">
            <Kpi value={sc.n_planted} label="Planted" color="var(--accent)" />
            <Kpi value={sc.caught} label="Caught" color="var(--pass)" />
            <Kpi value={sc.false_alarms.length} label="False alarms" color={sc.false_alarms.length ? "var(--fail)" : "var(--text-2)"} />
            <Kpi value={sc.reviews.length} label="To review" color="var(--review)" />
          </div>
        </div>
        <div className="card pad">
          <div className="card-head">
            <div className="card-title"><Target /> Answer key</div>
            <button className="btn btn-sm" onClick={() => setReveal(!reveal)}>{reveal ? <><EyeOff /> Hide</> : <><Eye /> Reveal</>}</button>
          </div>
          <div className={`answer${reveal ? "" : " hidden"}`}>
            {sc.planted.length === 0 && <div className="small muted">No faults planted. A perfect run is 41 PASS.</div>}
            {sc.planted.map((x) => (
              <div key={x.item} className="answer-row">
                {x.caught ? <CheckCircle2 size={17} style={{ color: "var(--pass)" }} /> : <XCircle size={17} style={{ color: "var(--fail)" }} />}
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="small">{x.text}</div>
                  <div className="tiny faint mono">{x.item} → {x.result}: {x.found}</div>
                </div>
              </div>
            ))}
            {!reveal && <div className="answer-cover"><EyeOff size={18} /> Hidden until you reveal it. Ask the jury to guess first.</div>}
          </div>
          {sc.reviews.length > 0 && <div className="tiny muted" style={{ marginTop: 10 }}>Sent to REVIEW (re-photo, not a FAIL): <span className="mono">{sc.reviews.join(", ")}</span></div>}
        </div>
        <div className="card pad">
          <div className="card-title" style={{ marginBottom: 10 }}>What the engine reported</div>
          {issues.length === 0 ? <div className="small muted">41 / 41 PASS</div> : issues.map((it) => (
            <button key={it.id} className="rc-row" onClick={() => { setSel(it.id); setFk((k) => k + 1); }}>
              <span className="marker" style={{ ["--c" as string]: STATUS_COLOR[statusOf(it)], width: 22, height: 22, fontSize: 11 }}>{it.marker}</span>
              <span className="mono small">{it.id}</span>
              <span className="tiny faint ellipsis grow">{it.found}</span>
              <StatusBadge s={statusOf(it)} />
            </button>
          ))}
        </div>
        {others.length > 1 && (
          <div className="card pad">
            <div className="card-title" style={{ marginBottom: 10 }}>This batch</div>
            {others.map((m) => {
              const s = m.forge!.score;
              const ok = s.caught === s.n_planted && !s.false_alarms.length;
              return (
                <a key={m.id} className="rc-row" href={`#/run/${m.id}`}>
                  {ok ? <CheckCircle2 size={16} style={{ color: "var(--pass)" }} /> : <XCircle size={16} style={{ color: "var(--fail)" }} />}
                  <span className="mono small">#{m.forge!.seed}</span>
                  <span className="tiny faint grow">{s.caught}/{s.n_planted} caught · {s.false_alarms.length} FA · {s.reviews.length} review</span>
                </a>
              );
            })}
          </div>
        )}
      </div>
    </motion.div>
  );
}

function SelfTest() {
  const { data } = useAsync(api.selftest);
  const s = data?.summary;
  if (!s) return null;
  return (
    <div className="stack" style={{ ["--gap" as string]: "18px" }}>
      <div className="selftest-kpis">
        <Kpi value={s.caught} label={`of ${s.planted} faults caught`} color="var(--pass)" note={`${(s.recall * 100).toFixed(0)}% recall`} />
        <Kpi value={s.false_alarms} label="false alarms" color="var(--accent)" note={`over ${s.correct_items.toLocaleString()} correct items`} />
        <Kpi value={s.reviews} label="sent to review" color="var(--review)" note={`${(s.review_rate * 100).toFixed(1)}% of correct items`} />
        <Kpi value={s.clean_cabinets_zero_fail} label={`of ${s.clean_cabinets} clean cabinets`} color="var(--pass)" note="came back with zero FAIL" />
        <Kpi value={s.sec_per_cabinet ?? 0} decimals={1} suffix="s" label="per cabinet" color="var(--accent-3)" note={`${s.cpu_cores ?? "?"}-core CPU, no GPU`} />
      </div>
      <div className="selftest-grid">
        <div className="card pad">
          <div className="card-title" style={{ marginBottom: 16 }}>Recall by fault type</div>
          <div className="bars">
            {Object.entries(s.per_type).sort((a, b) => b[1][1] - a[1][1]).map(([k, [c, n]], i) => (
              <div key={k} className="bar-row">
                <span className="small">{TYPE_LABEL[k] ?? k}</span>
                <div className="bar"><motion.i initial={{ width: 0 }} whileInView={{ width: `${(c / n) * 100}%` }} viewport={{ once: true }} transition={{ duration: 0.9, delay: i * 0.06 }} /></div>
                <span className="mono small">{c}/{n}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="card pad">
          <div className="card-head">
            <div className="card-title">50 unseen cabinets</div>
            <div className="legend tiny faint">
              <span><i className="cell ok" /> all caught</span>
              <span><i className="cell clean" /> clean, 0 FAIL</span>
              <span><i className="cell rv" /> has a REVIEW</span>
            </div>
          </div>
          <div className="cells">
            {data!.cabinets.map((c, i) => {
              const cls = c.false_alarms || c.caught < c.planted ? "bad" : c.planted === 0 ? "clean" : "ok";
              return (
                <motion.div key={c.i} className={`cell ${cls}${c.reviews ? " rv" : ""} tip`} initial={{ opacity: 0, scale: 0.5 }} whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true }} transition={{ delay: i * 0.012 }}
                  data-tip={`#${c.i} · camera ${c.strength}\n${c.planted ? c.faults.join("\n") : "no faults"}\ncaught ${c.caught}/${c.planted} · ${c.reviews} review`}>
                  <span>{c.planted || ""}</span>
                </motion.div>
              );
            })}
          </div>
          <div className="tiny faint" style={{ marginTop: 12 }}>Number = faults planted. Every 5th cabinet is fault-free. Camera angle, light, colour cast, blur and JPEG noise are random.</div>
        </div>
      </div>
      <div className="code"><span className="c"># reproduce the self-test (held-out seeds 200-249)</span>{"\n"}python eval_forge.py 50 200</div>
    </div>
  );
}

export function Forge() {
  const toast = useToast();
  const [faults, setFaults] = useState<number | null>(null);
  const [strength, setStrength] = useState(1.0);
  const [count, setCount] = useState(1);
  const [seed, setSeed] = useState("");
  const [job, setJob] = useState<JobView | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ p: RunPayload; metas: RunPayload["meta"][] } | null>(null);
  const live = useAsync(api.forgeLive);

  const go = async () => {
    setBusy(true);
    setResult(null);
    try {
      const j = await api.forge({ faults, strength, seed: seed ? +seed : null, count });
      setJob(j);
      const done = await followJob(j.id, setJob);
      if (done.status === "error") throw new Error(done.error ?? "Forge failed");
      const last = await api.run(done.runs[done.runs.length - 1]);
      const metas = await Promise.all(done.runs.map((r) => api.run(r).then((x) => x.meta)));
      setResult({ p: last, metas });
      live.reload();
    } catch (e) {
      toast("error", (e as Error).message);
    } finally {
      setBusy(false);
      setJob(null);
    }
  };

  const lastRun = job?.runs?.length ? job.runs[job.runs.length - 1] : null;
  const L = live.data;

  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">Fault Forge</span>
          <h1>Plant hidden faults. Watch it find them.</h1>
          <p>Fault Forge builds a cabinet the engine has never seen, plants random faults, shoots it with a random camera angle, light, colour cast and blur, then scores the inspection against the hidden answer key. It is how we measure ourselves before Emerson's hidden test.</p>
        </div>
      </div>

      <div className="forge-top">
        <div className="card pad forge-ctl">
          <div className="card-title" style={{ marginBottom: 18 }}><FlaskConical /> Forge a cabinet</div>
          <label className="ctl">
            <span>Faults to plant</span>
            <Seg value={faults ?? -1} onChange={(v) => setFaults(v === -1 ? null : v)} options={[
              { value: -1, label: <><Dices /> Random</> }, { value: 0, label: "0" }, { value: 1, label: "1" }, { value: 2, label: "2" }, { value: 3, label: "3" }, { value: 4, label: "4" },
            ]} />
          </label>
          <label className="ctl">
            <span className="row between">Camera difficulty <b className="mono small">{strength.toFixed(2)} · {strengthLabel(strength)}</b></span>
            <input className="range" type="range" min={0.8} max={1.4} step={0.05} value={strength} onChange={(e) => setStrength(+e.target.value)} style={{ ["--p" as string]: `${((strength - 0.8) / 0.6) * 100}%` }} />
            <span className="row between tiny faint"><span>0.8 gentle</span><span>self-test range</span><span>1.4 brutal</span></span>
          </label>
          <label className="ctl">
            <span>Cabinets</span>
            <Seg value={count} onChange={setCount} options={[{ value: 1, label: "1" }, { value: 3, label: "3" }, { value: 5, label: "5" }, { value: 10, label: "10" }]} />
          </label>
          <label className="ctl">
            <span>Seed <span className="faint">(optional, for a reproducible cabinet)</span></span>
            <div className="row" style={{ ["--gap" as string]: "6px" }}>
              <input className="input grow mono" inputMode="numeric" placeholder="random" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, "").slice(0, 7))} />
              <button className="btn btn-icon" onClick={() => setSeed(String(10000 + Math.floor(Math.random() * 89999)))} title="Random seed"><Dices /></button>
            </div>
          </label>
          {STATIC && (
            <div className="tiny muted">Showcase: picks one of the unseen cabinets Fault Forge generated and the real engine inspected (recorded), matching your fault count. Live forging with any seed and camera runs in the local engine.</div>
          )}
          <button className="btn btn-primary btn-xl btn-block" onClick={go} disabled={busy}>
            <Play /> {busy ? "Forging…" : count > 1 ? `Forge & inspect ${count} cabinets` : "Forge & inspect"}
          </button>
        </div>
        <div className="card pad forge-live">
          <div className="card-head">
            <div>
              <div className="card-title"><Gauge /> Live tally on this machine</div>
              <div className="card-sub">Every Fault Forge cabinet inspected here, scored against its answer key.</div>
            </div>
          </div>
          <div className="forge-kpis">
            <Kpi value={L?.cabinets ?? 0} label="Cabinets" color="var(--accent)" />
            <Kpi value={L?.caught ?? 0} label={`of ${L?.planted ?? 0} caught`} color="var(--pass)" />
            <Kpi value={L?.false_alarms ?? 0} label="False alarms" color={L?.false_alarms ? "var(--fail)" : "var(--text-2)"} />
            <Kpi value={L?.reviews ?? 0} label="To review" color="var(--review)" />
          </div>
          <div className="live-runs">
            <AnimatePresence initial={false}>
              {L?.runs.slice(0, 18).map((r) => {
                const ok = r.caught === r.planted && !r.false_alarms;
                return (
                  <motion.a key={r.id} href={`#/run/${r.id}`} className={`live-run${ok ? "" : " bad"}`} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} title={`Seed ${r.seed}: ${r.caught}/${r.planted} caught, ${r.false_alarms} false alarms`}>
                    {ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                    <span className="mono">{r.caught}/{r.planted}</span>
                  </motion.a>
                );
              })}
            </AnimatePresence>
            {!L?.runs.length && <div className="tiny faint">No cabinets forged yet. Press “Forge & inspect”.</div>}
          </div>
        </div>
      </div>

      {busy && (
        <div style={{ marginTop: 22 }}>
          <Running job={job} photo={lastRun ? url.file(lastRun, "photo", 1200) : url.sample("02", 1200)} enabled={["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"]} title={count > 1 ? `Forging ${count} unseen cabinets` : "Forging an unseen cabinet"} />
        </div>
      )}
      {result && !busy && <div style={{ marginTop: 22 }}><Result p={result.p} others={result.metas} /></div>}

      <section className="section">
        <Reveal className="section-head">
          <span className="eyebrow">Offline self-test</span>
          <h2>50 cabinets it had never seen.</h2>
          <p>The same harness, run in bulk. These are generated cabinets that copy Emerson's example layout; at the finale we re-run it on Emerson's real samples.</p>
        </Reveal>
        <SelfTest />
      </section>
      <div className="tiny faint row" style={{ ["--gap" as string]: "6px", marginTop: 18 }}><Terminal size={13} /> Live tally and history are stored in <span className="mono">out/runs/</span>.</div>
    </div>
  );
}
