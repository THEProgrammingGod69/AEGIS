import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ClipboardCheck, Inbox, ListChecks, ScrollText, ShieldQuestion, UserCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ProofCard } from "../components/ProofCard";
import { Kpi, Marker, StatusBadge, useToast } from "../components/ui";
import { api } from "../lib/api";
import { STATUS_COLOR, runDate } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { inspectorName, setInspectorName } from "../lib/reviews";
import { go } from "../lib/router";
import type { Result, Review as ReviewT, RunMeta, RunPayload } from "../lib/types";

type Tab = "review" | "confirm" | "audit";

interface Entry {
  run: RunMeta;
  item: string;
  result: Result;
  found: string;
  marker: number;
  review?: ReviewT;
}

/**
 * Review station: the engine sends what it cannot decide to REVIEW instead of guessing; a person closes the loop.
 * FAILs can be confirmed (or overturned) too, and every decision is kept with who and when.
 */
export function Review() {
  const toast = useToast();
  const runs = useAsync(() => api.runs(500));
  const [tab, setTab] = useState<Tab | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [name, setName] = useState(inspectorName());
  const [note, setNote] = useState("");
  const [payloads, setPayloads] = useState<Record<string, RunPayload>>({});

  const all = useMemo<Entry[]>(() => {
    const out: Entry[] = [];
    for (const m of runs.data ?? []) {
      for (const i of m.issues) {
        if (i.result !== "FAIL" && i.result !== "REVIEW") continue;
        if (i.recheck === "CLOSED") continue;
        out.push({ run: m, item: i.id, result: i.result, found: i.found, marker: i.marker, review: m.reviews?.[i.id] });
      }
    }
    return out;
  }, [runs.data]);

  const lists: Record<Tab, Entry[]> = {
    review: all.filter((e) => e.result === "REVIEW" && !e.review),
    confirm: all.filter((e) => e.result === "FAIL" && !e.review),
    audit: all.filter((e) => e.review).sort((a, b) => b.review!.at.localeCompare(a.review!.at)),
  };
  const t: Tab = tab ?? (lists.review.length ? "review" : "confirm");
  const list = lists[t];
  const key = (e: Entry) => `${e.run.id}/${e.item}`;
  const cur = list.find((e) => key(e) === sel) ?? list[0] ?? null;

  useEffect(() => {
    if (!cur || payloads[cur.run.id]) return;
    api.run(cur.run.id).then((p) => setPayloads((x) => ({ ...x, [cur.run.id]: p }))).catch(() => {});
  }, [cur, payloads]);
  useEffect(() => setNote(cur?.review?.note ?? ""), [cur?.run.id, cur?.item]); // eslint-disable-line react-hooks/exhaustive-deps

  const decide = useCallback(async (d: ReviewT["decision"] | "CLEAR") => {
    if (!cur) return;
    if (cur.item === "REG-DRAWING" && d !== "CLEAR") { toast("error", "Drawing alignment must be resolved by a new inspection with matching inputs."); return; }
    try {
      const idx = list.indexOf(cur);
      await api.review(cur.run.id, cur.item, d, note, name);
      toast("ok", d === "CLEAR" ? `Decision on ${cur.item} cleared` : `${cur.item}: ${d} · ${name}`);
      const next = t === "audit" ? cur : list[idx + 1] ?? list[idx - 1];
      setSel(next ? key(next) : null);
      setNote("");
      runs.reload();
    } catch (e) {
      toast("error", (e as Error).message);
    }
  }, [cur, list, note, name, t, toast, runs]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "TEXTAREA" || e.metaKey || e.ctrlKey) return;
      if (e.key === "p" && t !== "audit") { e.preventDefault(); void decide("PASS"); }
      if (e.key === "f" && t !== "audit") { e.preventDefault(); void decide("FAIL"); }
      if (e.key === "ArrowDown" || e.key === "j" || e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        const i = cur ? list.indexOf(cur) : -1;
        const n = list[(i + (e.key === "ArrowDown" || e.key === "j" ? 1 : -1) + list.length) % Math.max(1, list.length)];
        if (n) setSel(key(n));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [decide, cur, list, t]);

  const decided = lists.audit;
  const judged = decided.filter((e) => e.result === "FAIL");       // the engine took a position on these
  const agree = judged.filter((e) => e.review!.decision === "FAIL").length;
  const p = cur ? payloads[cur.run.id] : undefined;
  const it = p?.results.find((r) => r.id === cur?.item);

  return (
    <div className="main">
      <div className="page-head">
        <div>
          <span className="eyebrow">Review station</span>
          <h1>Resolve uncertain evidence with an inspection.</h1>
          <p>Items EAGLE EYE could not decide land here as REVIEW instead of a guessed FAIL. An inspector looks at the drawing-vs-photo proof, decides, and leaves a note. FAILs can be confirmed or overturned too; every decision is kept with who and when.</p>
        </div>
        <label className="ctl" style={{ minWidth: 240 }}>
          <span className="tiny faint">Signed in as</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => setInspectorName(name)} placeholder="Inspector name" maxLength={80} />
        </label>
      </div>

      <div className="review-kpis">
        <Kpi value={lists.review.length} label="need a decision" color="var(--review)" note="REVIEW items" />
        <Kpi value={lists.confirm.length} label="FAILs to confirm" color="var(--fail)" note="before the work order" />
        <Kpi value={decided.length} label="decisions logged" color="var(--accent-3)" note="audit trail" />
        <Kpi value={judged.length ? (agree / judged.length) * 100 : 100} suffix="%" label="FAILs the inspector confirmed" color="var(--pass)" note={judged.length ? `${agree} of ${judged.length} reviewed FAILs` : "no FAILs reviewed yet"} />
      </div>

      <div className="review-grid">
        <div className="card review-queue">
          <div className="tabs">
            {([
              ["review", <><ShieldQuestion size={14} /> Review</>, lists.review.length],
              ["confirm", <><ListChecks size={14} /> FAILs</>, lists.confirm.length],
              ["audit", <><ScrollText size={14} /> Audit</>, decided.length],
            ] as const).map(([k, l, n]) => (
              <button key={k} className={`tab${t === k ? " on" : ""}`} onClick={() => { setTab(k); setSel(null); }}>
                {l} <span className="mono">{n}</span>
                {t === k && <motion.i layoutId="rv-u" className="tab-u" />}
              </button>
            ))}
          </div>
          <div className="review-list">
            {runs.loading && !runs.data && <div className="skeleton" style={{ height: 200 }} />}
            {runs.data && !list.length && (
              <div className="empty">
                <Inbox />
                <div className="small muted">
                  {t === "review" ? "No REVIEW items in this queue. Check each run for unobserved or skipped requirements." : t === "confirm" ? "No unconfirmed FAILs." : "No decisions yet."}
                </div>
                {t === "review" && lists.confirm.length > 0 && <button className="btn btn-sm" onClick={() => setTab("confirm")}>Confirm {lists.confirm.length} FAILs instead</button>}
                {!all.length && <button className="btn btn-sm btn-primary" onClick={() => go("inspect")}>Run an inspection</button>}
              </div>
            )}
            {list.map((e) => {
              const s = e.review?.decision ?? e.result;
              return (
                <button key={key(e)} className={`rq-row${cur && key(cur) === key(e) ? " on" : ""}`} onClick={() => setSel(key(e))} style={{ ["--c" as string]: STATUS_COLOR[s] }}>
                  <Marker n={e.marker} s={e.result} />
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div className="row between">
                      <span className="mono small">{e.item}</span>
                      {e.review ? <StatusBadge s={e.review.decision} label={`${e.review.decision === e.result ? "✓" : "↺"} ${e.review.decision}`} /> : <StatusBadge s={e.result} />}
                    </div>
                    <div className="tiny muted ellipsis">{e.found}</div>
                    <div className="tiny faint ellipsis">{e.run.label} · {e.review ? `${e.review.by} · ${runDate(e.review.at)}` : runDate(e.run.created)}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="stack" style={{ ["--gap" as string]: "16px" }}>
          <AnimatePresence mode="wait">
            {cur ? (
              <motion.div key={key(cur)} className="card pad" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <div className="row between wrap" style={{ marginBottom: 14, ["--gap" as string]: "8px" }}>
                  <div className="tiny faint">Run <a href={`#/run/${cur.run.id}`} className="mono">{cur.run.id}</a> · {cur.run.label} · {cur.run.cabinet}</div>
                  <a className="btn btn-sm btn-ghost" href={`#/run/${cur.run.id}`}>Open inspection</a>
                </div>
                {p && it ? <ProofCard run={cur.run.id} it={it} geo={{ photoSize: p.photo_size, sizeMm: p.size_mm }} /> : <div className="skeleton" style={{ height: 380 }} />}
                {cur.item === "REG-DRAWING" ? <div className="decide"><p className="small muted">This is an input or alignment blocker. Start a new inspection with the matching drawing; a component PASS or FAIL decision cannot resolve it.</p><button className="btn btn-primary" onClick={() => go("inspect")}>Select matching inputs</button></div> : <div className="decide">
                  <textarea className="input" rows={2} placeholder={cur.result === "REVIEW" ? "What did you see on the cabinet? (kept in the audit trail)" : "Why do you confirm / overturn? (optional)"} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
                  <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
                    <button className="btn btn-lg decide-pass" onClick={() => void decide("PASS")}><CheckCircle2 /> {cur.result === "FAIL" ? "Overturn: it is correct" : "PASS: it is correct"} <kbd>P</kbd></button>
                    <button className="btn btn-lg decide-fail" onClick={() => void decide("FAIL")}><XCircle /> {cur.result === "FAIL" ? "Confirm FAIL" : "FAIL: it is wrong"} <kbd>F</kbd></button>
                    {cur.review && <button className="btn btn-lg btn-ghost" onClick={() => void decide("CLEAR")}>Undo decision</button>}
                    <span className="tiny faint grow" style={{ textAlign: "right" }}><kbd>↑</kbd> <kbd>↓</kbd> move through the queue</span>
                  </div>
                </div>}
              </motion.div>
            ) : (
              <motion.div key="none" className="card pad empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                <ClipboardCheck />
                <div className="muted">Queue empty.</div>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="card pad small muted row" style={{ ["--gap" as string]: "10px", alignItems: "flex-start" }}>
            <UserCheck size={18} style={{ flexShrink: 0, color: "var(--accent-3)" }} />
            <span>Decisions feed the work order (overturned FAILs drop out, confirmed REVIEWs become fixes) and the agreement rate in Analytics. The engine's own report stays untouched, so the audit trail always shows what the machine said and what the person decided.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
