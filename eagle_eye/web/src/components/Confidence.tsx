/** Calibrated confidence on the run page: a chip per item and the per-photo line in the verdict banner. */
import { Gauge } from "lucide-react";
import { confidenceColor, confidenceMeaning, engineOf, itemConfidence, pct, photoConfidence, type Engine } from "../lib/confidence";
import type { Item, RunPayload } from "../lib/types";

export function ConfidenceChip({ it, eng, wide }: { it: Item; eng: Engine; wide?: boolean }) {
  const c = itemConfidence(it, eng);
  if (c == null) return <span className="tiny faint">not judged</span>;
  const color = confidenceColor(c, it.result);
  return (
    <span className={`conf-chip tip${wide ? " wide" : ""}`} style={{ ["--c" as string]: color }}
      data-tip={`${pct(c)} ${confidenceMeaning(it.result)}\ncalibrated on Fault Forge runs · raw engine score ${Math.round((it.conf ?? 0) * 100)}%`}>
      <i className="conf-meter"><b style={{ width: `${Math.max(4, c * 100)}%` }} /></i>
      <span className="mono">{pct(c)}</span>
      {wide && <span className="tiny faint">{it.result === "REVIEW" ? "fault likelihood" : "confidence"}</span>}
    </span>
  );
}

export function PhotoConfidenceLine({ p }: { p: RunPayload }) {
  const pc = photoConfidence(p);
  if (!pc) return null;
  const color = pc.score >= 0.95 ? "var(--pass)" : pc.score >= 0.85 ? "var(--review)" : "var(--fail)";
  const weakest = pc.lowest.filter((l) => l.confidence < 0.9);
  return (
    <div className="photo-conf" style={{ ["--c" as string]: color }}>
      <Gauge size={15} />
      <span className="photo-conf-score mono">{pct(pc.score)}</span>
      <span className="small">
        photo confidence across {pc.decided} PASS/FAIL verdicts · about {pc.expected_errors.toFixed(1)} may be wrong
        {pc.review > 0 && <> · {pc.review} sent to REVIEW</>}
        {weakest.length > 0 && <> · least certain: {weakest.map((l) => `${l.id} ${pct(l.confidence)}`).join(", ")}</>}
      </span>
      <span className="tiny faint tip" data-tip={`Calibrated on Fault Forge runs (${engineOf(p) === "real" ? "real-cabinet" : "demo-cabinet"} engine): a 90% verdict is right about 90% of the time. See Fault Forge → Confidence calibration.`}>calibrated</span>
    </div>
  );
}
