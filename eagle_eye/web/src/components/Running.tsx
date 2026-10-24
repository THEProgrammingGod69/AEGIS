import { motion } from "framer-motion";
import { Cloud, Clock, Cpu, Loader2, PlayCircle } from "lucide-react";
import { useElapsed } from "../lib/hooks";
import type { JobView } from "../lib/types";
import { Pipeline } from "./Pipeline";

/** Live view of an inspection job: the photo being scanned + the 6-stage pipeline filling in. */
export function Running({ job, photo, enabled, title }: { job: JobView | null; photo: string; enabled: string[]; title: string }) {
  const running = !job || job.status === "queued" || job.status === "running";
  const t = useElapsed(running);
  const recheck = job?.kind === "recheck";
  const cab = job?.events.filter((e) => e.stage === "cabinet").slice(-1)[0];
  return (
    <div className="running-view">
      <motion.div className="card running-photo" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
        <img src={photo} alt="Cabinet photo being inspected" />
        <div className="scan"><div className="scan-beam" /><div className="scan-grid" /></div>
        <div className="corners"><i /><i /><i /><i /></div>
      </motion.div>
      <motion.div className="card pad running-side" initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}>
        <div className="row between" style={{ marginBottom: 18 }}>
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
        {job?.note && <div className="queued">{job.note}</div>}
        {job?.status === "queued" && job.queue_position > 0 && (
          <div className="queued"><Loader2 size={14} className="spin" /> Waiting for {job.queue_position} inspection(s) ahead</div>
        )}
        <Pipeline events={job?.events ?? []} enabled={enabled} recheck={recheck} />
      </motion.div>
    </div>
  );
}
