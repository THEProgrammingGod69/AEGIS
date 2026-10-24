import { motion } from "framer-motion";
import { ArrowRight, FlaskConical, History as HistoryIcon, ImageIcon, RefreshCcw, ScanEye, Sparkles, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Seg, StatusBadge, useToast } from "../components/ui";
import { STATIC, api, followJob, url } from "../lib/api";
import { pct } from "../lib/confidence";
import { STATUS_COLOR, runDate } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { go } from "../lib/router";
import type { JobView, RunMeta } from "../lib/types";

type Filter = "all" | "showcase" | "inspect" | "recheck" | "forge";

export function History() {
  const toast = useToast();
  const { data, reload, loading } = useAsync(() => api.runs(500));
  const [f, setF] = useState<Filter>("all");
  const [job, setJob] = useState<JobView | null>(null);

  const chains = useMemo(() => {
    const by = new Map<string, RunMeta[]>();
    (data ?? []).forEach((m) => {
      const k = m.root || m.id;
      by.set(k, [...(by.get(k) ?? []), m]);
    });
    const caseOf = (c: RunMeta[]) => c.find((m) => m.showcase)?.showcase?.n ?? 99;
    return [...by.values()]
      .map((c) => c.sort((a, b) => a.version - b.version || a.id.localeCompare(b.id)))
      .sort((a, b) => (f === "showcase" ? caseOf(a) - caseOf(b) : 0) || b[b.length - 1].id.localeCompare(a[a.length - 1].id))
      .filter((c) => f === "all" || (f === "showcase" ? c.some((m) => m.showcase) : f === "forge" ? c[0].source === "forge"
        : f === "recheck" ? c.length > 1 : c[0].source !== "forge"));
  }, [data, f]);

  const loadShowcase = async () => {
    try {
      const j = await api.showcase();
      setJob(j);
      const done = await followJob(j.id, setJob);
      const rows = done.showcase ?? [];
      const bad = rows.filter((r) => !r.ok);
      if (done.status === "error") toast("error", done.error ?? "Showcase failed");
      else toast(bad.length ? "error" : "ok", `${rows.length - bad.length} of ${rows.length} showcase cases behaved as expected` +
        (bad.length ? `: check ${bad.map((r) => r.label.split(" · ")[1]).join(", ")}` : ""));
      setF("showcase");
      reload();
    } catch (e) {
      toast("error", String(e));
    } finally {
      setJob(null);
    }
  };
  const progress = job?.events.filter((e) => e.stage === "showcase" && e.status === "start").slice(-1)[0] as { index?: number; count?: number } | undefined;
  const showcaseBtn = !STATIC && (
    <button className="btn" onClick={loadShowcase} disabled={!!job} title="Clean cabinets and planted anomalies with their answer keys, for a demo">
      <Sparkles /> {job ? `Building case ${progress?.index ?? 1} of ${progress?.count ?? "…"}` : "Load showcase cases"}
    </button>
  );

  const clear = async () => {
    if (!window.confirm("Delete every stored inspection, re-check and Fault Forge run on this machine?")) return;
    const r = await api.clearRuns();
    toast("ok", `Deleted ${r.deleted} runs`);
    reload();
  };

  const n = data?.length ?? 0;
  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">History</span>
          <h1>Every inspection, every re-check.</h1>
          <p>Re-checks are chained to the inspection they verify, so the issue history of each cabinet reads left to right: v1 → v2 → v3.</p>
        </div>
        <div className="row wrap">
          <Seg value={f} onChange={setF} options={[
            { value: "all", label: "All" }, { value: "showcase", label: <><Sparkles /> Showcase</> }, { value: "inspect", label: <><ScanEye /> Inspections</> },
            { value: "recheck", label: <><RefreshCcw /> Re-check chains</> }, { value: "forge", label: <><FlaskConical /> Fault Forge</> },
          ]} />
          {showcaseBtn}
          <button className="btn btn-danger" onClick={clear} disabled={!n}><Trash2 /> Clear</button>
        </div>
      </div>

      {loading && !data && <div className="skeleton" style={{ height: 260 }} />}
      {data && chains.length === 0 && (
        <div className="card pad empty">
          <HistoryIcon />
          <div>{f === "showcase" ? "No showcase cases yet." : "No runs yet."}</div>
          <div className="row wrap" style={{ justifyContent: "center" }}>
            <button className="btn btn-primary" onClick={() => go("inspect")}>Run an inspection</button>
            {showcaseBtn}
          </div>
        </div>
      )}
      <div className="history-grid">
        {chains.map((c, ci) => (
          <motion.div key={c[0].id} className={`card pad chain-card${c.length > 1 ? " multi" : ""}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(ci, 10) * 0.04 }}>
            <div className="row between wrap" style={{ marginBottom: 14 }}>
              <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
                {c[0].showcase ? <Sparkles size={16} className="faint" /> : c[0].source === "forge" ? <FlaskConical size={16} className="faint" /> : <ImageIcon size={16} className="faint" />}
                <b>{c[0].label}</b>
                <span className="tag accent">{c[0].cabinet}</span>
                <span className="tiny faint">{runDate(c[0].created)}</span>
              </div>
              {c.length > 1 && <span className="tiny faint">{c.length} versions</span>}
            </div>
            {c.some((m) => m.showcase) && <ShowcaseNote c={c} />}
            <div className="versions">
              {c.map((m, i) => (
                <div key={m.id} className="row" style={{ ["--gap" as string]: "10px" }}>
                  {i > 0 && <ArrowRight size={16} className="faint" />}
                  <a className="version" href={`#/run/${m.id}`} style={{ ["--c" as string]: STATUS_COLOR[m.verdict.label] }}>
                    <div className="version-img"><img src={url.file(m.id, "marked", 320)} alt="" loading="lazy" /></div>
                    <div className="version-body">
                      <div className="row between">
                        <b className="mono">v{m.version}</b>
                        <StatusBadge s={m.verdict.label} />
                      </div>
                      <div className="tiny muted">{m.counts.FAIL} FAIL · {m.counts.REVIEW} REVIEW · {m.counts.PASS} PASS{m.confidence ? ` · ${pct(m.confidence.score)} confidence` : ""}</div>
                      {m.recheck && <div className="tiny" style={{ color: "var(--closed)" }}>{m.recheck.CLOSED} closed · <span style={{ color: "var(--open)" }}>{m.recheck.OPEN} open</span></div>}
                      {m.forge && <div className="tiny" style={{ color: m.forge.score.caught === m.forge.score.n_planted && !m.forge.score.false_alarms.length ? "var(--pass)" : "var(--fail)" }}>{m.forge.score.caught}/{m.forge.score.n_planted} planted caught</div>}
                      <div className="tiny faint">{runDate(m.created)}</div>
                    </div>
                  </a>
                </div>
              ))}
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

/** What a showcase case planted and what to look at (showcase.py); a re-check shows its own step. */
function ShowcaseNote({ c }: { c: RunMeta[] }) {
  const cases = c.filter((m) => m.showcase);
  const last = cases[cases.length - 1].showcase!;
  // a Fault Forge case's planted anomalies are its answer key
  const planted = cases.flatMap((m) => (m.showcase!.planted.length ? m.showcase!.planted : m.forge?.score.planted.map((p) => p.text) ?? []));
  return (
    <div className="showcase-note">
      <div className="small">{cases.map((m) => m.showcase!.story).join(" Then: ")}</div>
      {planted.length > 0 && (
        <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
          <span className="tiny faint">Planted</span>
          {[...new Set(planted)].map((p) => <span key={p} className="tag">{p}</span>)}
        </div>
      )}
      {planted.length === 0 && <div className="tiny faint">Nothing planted: a clean case.</div>}
      <div className="tiny"><b>Look at:</b> {last.look}</div>
    </div>
  );
}
