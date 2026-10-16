import { motion } from "framer-motion";
import { Check, Loader2 } from "lucide-react";
import { CHECK_TITLE } from "../lib/format";
import type { JobEvent } from "../lib/types";

type St = "pending" | "running" | "done";

export const STAGES = [
  { key: "parse", title: "Parse the drawing", sub: "Vector GA → exact list of expected items. No AI." },
  { key: "register", title: "Register the photo", sub: "Backplate outline, then labels & ferrules as anchors (RANSAC)." },
  { key: "check", title: "Plug-in checks", sub: "One narrow yes/no question per item, at a known spot." },
  { key: "consensus", title: "Consensus", sub: "FAIL only when evidence agrees; unclear → REVIEW." },
  { key: "report", title: "Report", sub: "Boxed photo, expected-vs-found proof, Excel, PDF." },
  { key: "recheck", title: "Re-check", sub: "Fixed items CLOSE, the rest stay OPEN, history kept." },
] as const;

interface Derived {
  key: string;
  status: St;
  detail?: string;
  t?: number;
  checks?: { name: string; status: St; detail?: string }[];
}

/** Turn the raw job event stream into per-stage state (only the latest cabinet for multi-cabinet jobs). */
export function derive(all: JobEvent[], enabled: string[], withRecheck: boolean): Derived[] {
  const lastCab = all.map((e) => e.stage).lastIndexOf("cabinet");
  const ev = lastCab >= 0 ? all.slice(lastCab + 1) : all;
  const find = (stage: string, status: string, extra?: (e: JobEvent) => boolean) =>
    ev.find((e) => e.stage === stage && e.status === status && (!extra || extra(e)));
  const st = (stage: string): St => (find(stage, "done") ? "done" : find(stage, "start") ? "running" : "pending");
  const out: Derived[] = [];

  const pd = find("parse", "done");
  out.push({ key: "parse", status: st("parse"), t: pd?.t,
    detail: pd ? `${pd.cabinet} · ${pd.devices} devices · ${pd.terminals} terminals · ${pd.rails} rail · ${pd.wires} wires` : undefined });

  const rd = find("register", "done");
  const outl = (rd?.outliers as string[] | undefined) ?? [];
  out.push({ key: "register", status: st("register"), t: rd?.t,
    detail: rd ? `${rd.anchors} anchors locked · ${rd.inliers} RANSAC inliers${outl.length ? ` · off-pattern: ${outl.join(", ")}` : ""}` : undefined });

  const checks = enabled.map((name) => {
    const d = find("check", "done", (e) => e.check === name);
    const s = find("check", "start", (e) => e.check === name);
    const c = d?.counts as Record<string, number> | undefined;
    return { name, status: (d ? "done" : s ? "running" : "pending") as St,
      detail: c ? [c.FAIL && `${c.FAIL} FAIL`, c.REVIEW && `${c.REVIEW} REVIEW`, c.SKIP && `${c.SKIP} SKIP`].filter(Boolean).join(" · ") || `${d!.items} PASS` : undefined };
  });
  const cAll = checks.every((c) => c.status === "done");
  const cAny = checks.some((c) => c.status !== "pending");
  out.push({ key: "check", status: cAll && checks.length ? "done" : cAny ? "running" : "pending", checks,
    t: ev.filter((e) => e.stage === "check" && e.status === "done").slice(-1)[0]?.t });

  const cd = find("consensus", "done");
  const cc = cd?.counts as Record<string, number> | undefined;
  out.push({ key: "consensus", status: cd ? "done" : cAll && checks.length ? "running" : "pending", t: cd?.t,
    detail: cc ? `${cc.FAIL} FAIL · ${cc.REVIEW} REVIEW · ${cc.SKIP} root-cause SKIP · ${cc.PASS} PASS` : undefined });

  const rp = find("report", "done");
  out.push({ key: "report", status: st("report"), t: rp?.t, detail: rp ? "Marked photo · proof snippets · filled checklist · PDF" : undefined });

  if (withRecheck) {
    const rc = find("recheck", "done");
    out.push({ key: "recheck", status: rc ? "done" : rp ? "running" : "pending", t: rc?.t,
      detail: rc ? `${rc.CLOSED} CLOSED · ${rc.OPEN} OPEN · ${rc.REGRESSION} REGRESSION · ${rc.NEW} NEW` : undefined });
  }
  return out;
}

function Node({ s, n }: { s: St; n: number }) {
  return (
    <div className={`pl-node ${s}`}>
      {s === "done" ? <Check size={15} strokeWidth={3} /> : s === "running" ? <Loader2 size={15} className="spin" /> : <span>{n}</span>}
    </div>
  );
}

export function Pipeline({ events, enabled, recheck }: { events: JobEvent[]; enabled: string[]; recheck: boolean }) {
  const stages = derive(events, enabled, recheck);
  return (
    <ol className="pipeline">
      {stages.map((d, i) => {
        const meta = STAGES.find((s) => s.key === d.key)!;
        return (
          <motion.li key={d.key} className={`pl-row ${d.status}`} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}>
            <div className="pl-rail">
              <Node s={d.status} n={i + 1} />
              {i < stages.length - 1 && (
                <div className="pl-line">
                  <motion.i initial={false} animate={{ height: d.status === "done" ? "100%" : "0%" }} transition={{ duration: 0.5 }} />
                </div>
              )}
            </div>
            <div className="pl-body">
              <div className="row between">
                <div className="pl-title">{meta.title}</div>
                {d.t != null && d.status === "done" && <span className="mono tiny faint">{d.t.toFixed(2)}s</span>}
              </div>
              <div className="pl-sub">{d.detail ?? meta.sub}</div>
              {d.checks && (
                <div className="pl-checks">
                  {d.checks.map((c) => (
                    <div key={c.name} className={`pl-check ${c.status}`}>
                      {c.status === "done" ? <Check size={12} strokeWidth={3} /> : c.status === "running" ? <Loader2 size={12} className="spin" /> : <i />}
                      <b className="mono">{c.name}</b>
                      <span>{c.detail ?? CHECK_TITLE[c.name] ?? ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}
