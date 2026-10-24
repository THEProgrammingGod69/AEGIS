import { motion } from "framer-motion";
import { Check, Cloud, Clock, Cpu, Loader2, PlayCircle } from "lucide-react";
import { useMemo, useRef } from "react";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { useElapsed } from "../lib/hooks";
import type { JobEvent, JobView } from "../lib/types";
import { EngineLog } from "./motion";
import { Pipeline, derive } from "./Pipeline";

const SHORT: Record<string, string> = {
  parse: "Parse", register: "Register", check: "Checks", consensus: "Consensus", report: "Report", recheck: "Re-check",
  kb: "Drawing", ocr: "OCR", place: "Place", agent: "Verify",
};

/** The events of the cabinet being inspected now (multi-cabinet jobs report one cabinet after another). */
const current = (all: JobEvent[]) => {
  const k = all.map((e) => e.stage).lastIndexOf("cabinet");
  return k >= 0 ? all.slice(k + 1) : all;
};

/** One log line per finished stage or check, in the order the engine reported them (append-only, so the
 *  typewriter only ever types new lines). */
function logLines(all: JobEvent[], enabled: string[], recheck: boolean) {
  const ev = current(all);
  const out: { t: string; k: string; v: string; tone?: "pass" | "fail" | "review" | "accent" }[] = [];
  ev.forEach((e, i) => {
    if (e.status !== "done" || e.stage === "cabinet") return;
    const d = derive(ev.slice(0, i + 1), enabled, recheck);
    const stage = d.find((s) => s.key === (e.stage === "parse" && ev.some((x) => x.engine === "real") ? "kb" : e.stage === "register" && ev.some((x) => x.engine === "real") ? "place" : e.stage));
    const check = e.check ? stage?.checks?.find((c) => c.name === e.check) : undefined;
    const v = check?.detail ?? stage?.detail ?? "done";
    out.push({
      t: `${(e.t ?? 0).toFixed(2)}s`,
      k: String(e.check ?? e.stage).toLowerCase(),
      v,
      tone: /\b[1-9]\d* FAIL/.test(v) ? "fail" : /\b[1-9]\d* REVIEW/.test(v) ? "review" : e.stage === "report" ? "accent" : undefined,
    });
  });
  return out;
}

/** Live view of an inspection job: the photo in a dark device with the scan beam following real progress (#29),
 *  a live stepper with a halo on the running stage, the engine log typing itself (#36) and the full pipeline. */
export function Running({ job, photo, enabled, title }: { job: JobView | null; photo: string; enabled: string[]; title: string }) {
  const running = !job || job.status === "queued" || job.status === "running";
  const t = useElapsed(running);
  const recheck = job?.kind === "recheck";
  const cab = job?.events.filter((e) => e.stage === "cabinet").slice(-1)[0];
  const events = job?.events ?? [];
  const stages = useMemo(() => derive(events, enabled, recheck), [events, enabled, recheck]);
  const lines = useMemo(() => logLines(events, enabled, recheck), [events, enabled, recheck]);
  const done = stages.filter((s) => s.status === "done").length;
  const busy = stages.filter((s) => s.status === "running").length;
  const progress = job?.status === "done" ? 1 : stages.length ? (done + 0.5 * busy) / stages.length : 0;
  const photoRef = useRef<HTMLDivElement>(null);

  // #29 the beam follows real progress events (0..1) instead of looping
  useGSAP(() => {
    const beam = photoRef.current!.querySelector(".scan-beam");
    if (calm()) return;
    gsap.to(beam, { yPercent: progress * 455, duration: 0.4, ease: "power2.out", overwrite: true });
  }, { scope: photoRef, dependencies: [progress] });

  return (
    <div className="running-view">
      <motion.div className="card running-photo device" ref={photoRef} initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
        <img src={photo} alt="Cabinet photo being inspected" />
        <div className="scan"><div className="scan-beam synced" /><div className="scan-grid" /></div>
        <div className="corners"><i /><i /><i /><i /></div>
        <div className="running-progress mono" aria-live="polite">{Math.round(progress * 100)}%</div>
      </motion.div>
      <motion.div className="running-side stack" style={{ ["--gap" as string]: "14px" }} initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}>
        <div className="card pad">
          <div className="row between" style={{ marginBottom: 16 }}>
            <div>
              <div className="row wrap" style={{ ["--gap" as string]: "8px" }}>
                <span className="eyebrow">{recheck ? "Re-check in progress" : job?.kind === "forge" ? "Fault Forge" : "Inspection in progress"}</span>
                {job?.mode === "cloud" && <span className="tag accent"><Cloud size={12} /> Live cloud engine</span>}
                {job?.mode === "recorded" && <span className="tag"><PlayCircle size={12} /> Recorded replay</span>}
                {!job?.mode && job && <span className="tag"><Cpu size={12} /> Local engine</span>}
              </div>
              <h2 className="running-title">{title}</h2>
              {cab && <div className="small muted">Cabinet {String(cab.index)} of {String(cab.count)}</div>}
            </div>
            <div className="running-clock">
              <Clock size={14} />
              <span className="mono">{(job?.status === "done" ? job.elapsed : t).toFixed(1)}s</span>
            </div>
          </div>
          <ol className="stepper" aria-label="Inspection stages">
            {stages.map((s, i) => (
              <li key={s.key} className={`step ${s.status}`}>
                <span className="step-node">{s.status === "done" ? <Check size={13} strokeWidth={3} /> : s.status === "running" ? <Loader2 size={13} className="spin" /> : i + 1}</span>
                <span className="step-label mono">{SHORT[s.key] ?? s.key}</span>
              </li>
            ))}
          </ol>
          {job?.note && <div className="queued">{job.note}</div>}
          {job?.status === "queued" && job.queue_position > 0 && (
            <div className="queued"><Loader2 size={14} className="spin" /> Waiting for {job.queue_position} inspection(s) ahead</div>
          )}
          <Pipeline events={events} enabled={enabled} recheck={recheck} />
        </div>
        <EngineLog lines={lines} title="ENGINE LOG · LIVE" startOnView={false} />
      </motion.div>
    </div>
  );
}
