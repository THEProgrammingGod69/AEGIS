import { motion } from "framer-motion";
import { Draggable } from "gsap/Draggable";
import { InertiaPlugin } from "gsap/InertiaPlugin";
import { CheckCircle2, ClipboardCheck, Hand, Inbox, ListChecks, ScrollText, ShieldQuestion, UserCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ProofCard } from "../components/ProofCard";
import { Kpi, Marker, StatusBadge, useToast } from "../components/ui";
import { api } from "../lib/api";
import { STATUS_COLOR, runDate, tone } from "../lib/format";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { useAsync } from "../lib/hooks";
import { inspectorName, setInspectorName } from "../lib/reviews";
import { go } from "../lib/router";
import type { Result, Review as ReviewT, RunMeta, RunPayload } from "../lib/types";

gsap.registerPlugin(Draggable, InertiaPlugin);

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
    if (!cur) return false;
    if (cur.item === "REG-DRAWING" && d !== "CLEAR") { toast("error", "Drawing alignment must be resolved by a new inspection with matching inputs."); return false; }
    try {
      const idx = list.indexOf(cur);
      await api.review(cur.run.id, cur.item, d, note, name);
      toast("ok", d === "CLEAR" ? `Decision on ${cur.item} cleared` : `${cur.item}: ${d} · ${name}`);
      const next = t === "audit" ? cur : list[idx + 1] ?? list[idx - 1];
      setSel(next ? key(next) : null);
      setNote("");
      runs.reload();
      return true;
    } catch (e) {
      toast("error", (e as Error).message);
      return false;
    }
  }, [cur, list, note, name, t, toast, runs]);

  /* #35 review swipe cards: drag the proof card left for PASS, right for FAIL. It rotates with the drag, a stamp fades
     in, and past 140 px it flies off and records the decision; otherwise it springs back. The P / F keys fling it too. */
  const cardRef = useRef<HTMLDivElement>(null);
  const decideRef = useRef(decide);
  decideRef.current = decide;
  const swipeable = !!cur && t !== "audit" && cur.item !== "REG-DRAWING";
  const fling = useCallback((d: "PASS" | "FAIL") => {
    const card = cardRef.current;
    if (!card || calm() || !swipeable) return void decideRef.current(d);
    const dir = d === "PASS" ? -1 : 1;
    gsap.set(card.querySelector(d === "PASS" ? ".stamp-pass" : ".stamp-fail"), { opacity: 1 });
    gsap.to(card, {
      x: dir * (card.offsetWidth + 120), rotation: dir * 14, opacity: 0, duration: 0.35, ease: "power2.in",
      onComplete: () => void decideRef.current(d).then((ok) => { if (!ok) gsap.to(card, { x: 0, rotation: 0, opacity: 1, duration: 0.6, ease: "elastic.out(1, 0.6)" }); }),
    });
  }, [swipeable]);

  useGSAP(() => {
    const card = cardRef.current;
    if (!card) return;
    if (!calm()) gsap.from(card, { y: 14, opacity: 0, duration: 0.45, ease: "expo.out" });
    if (!swipeable) return;
    const pass = card.querySelector(".stamp-pass");
    const fail = card.querySelector(".stamp-fail");
    Draggable.create(card, {
      type: "x", inertia: !calm(), dragClickables: false, zIndexBoost: false,
      onDrag() {
        gsap.set(this.target, { rotation: this.x / 18 });
        gsap.set(pass, { opacity: gsap.utils.clamp(0, 1, -this.x / 140) });
        gsap.set(fail, { opacity: gsap.utils.clamp(0, 1, this.x / 140) });
      },
      onDragEnd() {
        if (Math.abs(this.x) > 140) {
          const d = this.x < 0 ? "PASS" : "FAIL";
          gsap.to(this.target, {
            x: this.x * 3, rotation: this.x / 6, opacity: 0, duration: 0.35,
            onComplete: () => void decideRef.current(d).then((ok) => {
              if (!ok) gsap.to(card, { x: 0, rotation: 0, opacity: 1, duration: 0.6, ease: "elastic.out(1, 0.6)" });
            }),
          });
        } else {
          gsap.to(this.target, { x: 0, rotation: 0, duration: 0.6, ease: "elastic.out(1, 0.6)" });
          gsap.to([pass, fail], { opacity: 0, duration: 0.2 });
        }
      },
    });
  }, { dependencies: [cur ? key(cur) : "", swipeable] });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT" || (e.target as HTMLElement).tagName === "TEXTAREA" || e.metaKey || e.ctrlKey) return;
      if (e.key === "p" && t !== "audit") { e.preventDefault(); fling("PASS"); }
      if (e.key === "f" && t !== "audit") { e.preventDefault(); fling("FAIL"); }
      if (e.key === "ArrowDown" || e.key === "j" || e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        const i = cur ? list.indexOf(cur) : -1;
        const n = list[(i + (e.key === "ArrowDown" || e.key === "j" ? 1 : -1) + list.length) % Math.max(1, list.length)];
        if (n) setSel(key(n));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fling, cur, list, t]);

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
                <button key={key(e)} className={`rq-row${cur && key(cur) === key(e) ? " on" : ""}`} onClick={() => setSel(key(e))} style={tone(STATUS_COLOR[s])}>
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
          {cur ? (
            <div className="swipe-zone">
              {swipeable && <div className="swipe-under" aria-hidden="true"><span className="pass"><CheckCircle2 size={16} /> PASS</span><span className="fail">FAIL <XCircle size={16} /></span></div>}
              <div key={key(cur)} ref={cardRef} className={`card pad review-card${swipeable ? " swipeable" : ""}`}>
                {swipeable && <><span className="swipe-stamp stamp-pass">PASS</span><span className="swipe-stamp stamp-fail">FAIL</span></>}
                <div className="row between wrap" style={{ marginBottom: 14, ["--gap" as string]: "8px" }}>
                  <div className="tiny faint">Run <a href={`#/run/${cur.run.id}`} className="mono">{cur.run.id}</a> · {cur.run.label} · {cur.run.cabinet}</div>
                  <div className="row" style={{ ["--gap" as string]: "8px" }}>
                    {swipeable && <span className="tiny faint row swipe-hint" style={{ ["--gap" as string]: "5px" }}><Hand size={13} /> swipe ← PASS · FAIL →</span>}
                    <a className="btn btn-sm btn-ghost" href={`#/run/${cur.run.id}`}>Open inspection</a>
                  </div>
                </div>
                {p && it ? <ProofCard run={cur.run.id} it={it} geo={{ photoSize: p.photo_size, sizeMm: p.size_mm }} /> : <div className="skeleton" style={{ height: 380 }} />}
              </div>
              <div className="card pad">
                {cur.item === "REG-DRAWING" ? <div className="decide flat"><p className="small muted">This is an input or alignment blocker. Start a new inspection with the matching drawing; a component PASS or FAIL decision cannot resolve it.</p><button className="btn btn-primary" onClick={() => go("inspect")}>Select matching inputs</button></div> : <div className="decide flat">
                  <textarea className="input" rows={2} placeholder={cur.result === "REVIEW" ? "What did you see on the cabinet? (kept in the audit trail)" : "Why do you confirm / overturn? (optional)"} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
                  <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
                    <button className="btn btn-lg decide-pass" onClick={() => fling("PASS")}><CheckCircle2 /> {cur.result === "FAIL" ? "Overturn: it is correct" : "PASS: it is correct"} <kbd>P</kbd></button>
                    <button className="btn btn-lg decide-fail" onClick={() => fling("FAIL")}><XCircle /> {cur.result === "FAIL" ? "Confirm FAIL" : "FAIL: it is wrong"} <kbd>F</kbd></button>
                    {cur.review && <button className="btn btn-lg btn-ghost" onClick={() => void decide("CLEAR")}>Undo decision</button>}
                    <span className="tiny faint grow" style={{ textAlign: "right" }}><kbd>↑</kbd> <kbd>↓</kbd> move through the queue</span>
                  </div>
                </div>}
              </div>
            </div>
          ) : (
            <motion.div key="none" className="card pad empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <ClipboardCheck />
              <div className="muted">Queue empty.</div>
            </motion.div>
          )}
          <div className="card pad small muted row" style={{ ["--gap" as string]: "10px", alignItems: "flex-start" }}>
            <UserCheck size={18} style={{ flexShrink: 0, color: "var(--accent-3)" }} />
            <span>Decisions feed the work order (overturned FAILs drop out, confirmed REVIEWs become fixes) and the agreement rate in Analytics. The engine's own report stays untouched, so the audit trail always shows what the machine said and what the person decided.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
