import { motion } from "framer-motion";
import { ArrowRight, FlaskConical, History as HistoryIcon, ImageIcon, RefreshCcw, ScanEye, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Seg, StatusBadge, useToast } from "../components/ui";
import { api, url } from "../lib/api";
import { STATUS_COLOR, runDate } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { go } from "../lib/router";
import type { RunMeta } from "../lib/types";

type Filter = "all" | "inspect" | "recheck" | "forge";

export function History() {
  const toast = useToast();
  const { data, reload, loading } = useAsync(() => api.runs(500));
  const [f, setF] = useState<Filter>("all");

  const chains = useMemo(() => {
    const by = new Map<string, RunMeta[]>();
    (data ?? []).forEach((m) => {
      const k = m.root || m.id;
      by.set(k, [...(by.get(k) ?? []), m]);
    });
    return [...by.values()]
      .map((c) => c.sort((a, b) => a.version - b.version || a.id.localeCompare(b.id)))
      .sort((a, b) => b[b.length - 1].id.localeCompare(a[a.length - 1].id))
      .filter((c) => f === "all" || (f === "forge" ? c[0].source === "forge" : f === "recheck" ? c.length > 1 : c[0].source !== "forge"));
  }, [data, f]);

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
            { value: "all", label: "All" }, { value: "inspect", label: <><ScanEye /> Inspections</> },
            { value: "recheck", label: <><RefreshCcw /> Re-check chains</> }, { value: "forge", label: <><FlaskConical /> Fault Forge</> },
          ]} />
          <button className="btn btn-danger" onClick={clear} disabled={!n}><Trash2 /> Clear</button>
        </div>
      </div>

      {loading && !data && <div className="skeleton" style={{ height: 260 }} />}
      {data && chains.length === 0 && (
        <div className="card pad empty">
          <HistoryIcon />
          <div>No runs yet.</div>
          <button className="btn btn-primary" onClick={() => go("inspect")}>Run an inspection</button>
        </div>
      )}
      <div className="history-grid">
        {chains.map((c, ci) => (
          <motion.div key={c[0].id} className={`card pad chain-card${c.length > 1 ? " multi" : ""}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(ci, 10) * 0.04 }}>
            <div className="row between wrap" style={{ marginBottom: 14 }}>
              <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
                {c[0].source === "forge" ? <FlaskConical size={16} className="faint" /> : <ImageIcon size={16} className="faint" />}
                <b>{c[0].label}</b>
                <span className="tag accent">{c[0].cabinet}</span>
                <span className="tiny faint">{runDate(c[0].created)}</span>
              </div>
              {c.length > 1 && <span className="tiny faint">{c.length} versions</span>}
            </div>
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
                      <div className="tiny muted">{m.counts.FAIL} FAIL · {m.counts.REVIEW} REVIEW · {m.counts.PASS} PASS</div>
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
