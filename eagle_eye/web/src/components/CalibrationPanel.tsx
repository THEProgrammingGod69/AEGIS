/** Confidence calibration from Fault Forge runs (eagle_eye/calibration.py): a reliability diagram of the engine's raw
 *  item score and of the calibrated confidence, both scored on held-out images, with the maps the console applies. */
import { Target } from "lucide-react";
import { useState } from "react";
import { CALIBRATION, pct } from "../lib/confidence";
import type { CalEngine, CurvePoint } from "../lib/types";
import { Kpi, Seg } from "./ui";

const S = 340;
const M = { l: 44, r: 14, t: 14, b: 40 };

function Diagram({ e }: { e: CalEngine }) {
  const pts = [...e.heldout.raw, ...e.heldout.cal];
  const lo = Math.min(0.5, ...pts.map((p) => Math.floor(Math.min(p.stated, p.observed) * 10) / 10));
  const iw = S - M.l - M.r;
  const ih = S - M.t - M.b;
  const x = (v: number) => M.l + ((v - lo) / (1 - lo)) * iw;
  const y = (v: number) => M.t + ih - ((v - lo) / (1 - lo)) * ih;
  const maxN = Math.max(1, ...pts.map((p) => p.n));
  const r = (n: number) => 3 + 7 * Math.sqrt(n / maxN);
  const path = (c: CurvePoint[]) => c.map((p, k) => `${k ? "L" : "M"}${x(p.stated).toFixed(1)},${y(p.observed).toFixed(1)}`).join(" ");
  const ticks: number[] = [];
  for (let v = lo; v <= 1.0001; v += 0.1) ticks.push(Math.round(v * 10) / 10);
  const tip = (kind: string, p: CurvePoint) => `${kind}: stated ${pct(p.stated)}, observed ${pct(p.observed)} right\n${p.n.toLocaleString()} held-out verdicts`;
  return (
    <svg className="calib-chart" viewBox={`0 0 ${S} ${S}`} role="img"
      aria-label={`Reliability diagram: raw score ECE ${pct(e.heldout.ece_raw ?? 0)}, calibrated ECE ${pct(e.heldout.ece_cal ?? 0)}`}>
      {ticks.map((t) => (
        <g key={t}>
          <line className="calib-gridline" x1={x(t)} x2={x(t)} y1={M.t} y2={M.t + ih} />
          <line className="calib-gridline" x1={M.l} x2={M.l + iw} y1={y(t)} y2={y(t)} />
          <text className="calib-axis" x={x(t)} y={M.t + ih + 16} textAnchor="middle">{Math.round(t * 100)}</text>
          <text className="calib-axis" x={M.l - 6} y={y(t) + 4} textAnchor="end">{Math.round(t * 100)}</text>
        </g>
      ))}
      <line className="calib-diag" x1={x(lo)} y1={y(lo)} x2={x(1)} y2={y(1)} />
      <text className="calib-axis" x={x(lo + 0.62 * (1 - lo)) + 8} y={y(lo + 0.62 * (1 - lo)) + 4}>perfect calibration</text>
      <path className="calib-raw" d={path(e.heldout.raw)} />
      {e.heldout.raw.map((p) => <circle key={`r${p.lo}`} className="calib-raw-dot tip" cx={x(p.stated)} cy={y(p.observed)} r={r(p.n)}><title>{tip("Raw score", p)}</title></circle>)}
      <path className="calib-cal" d={path(e.heldout.cal)} />
      {e.heldout.cal.map((p) => <circle key={`c${p.lo}`} className="calib-cal-dot" cx={x(p.stated)} cy={y(p.observed)} r={r(p.n)}><title>{tip("Calibrated", p)}</title></circle>)}
      <text className="calib-label" x={M.l + iw / 2} y={S - 6} textAnchor="middle">Stated confidence (%)</text>
      <text className="calib-label" x={12} y={M.t + ih / 2} textAnchor="middle" transform={`rotate(-90 12 ${M.t + ih / 2})`}>Observed: right (%)</text>
    </svg>
  );
}

export function CalibrationPanel() {
  const keys = (["demo", "real"] as const).filter((k) => CALIBRATION.engines[k]);
  const [eng, setEng] = useState<"demo" | "real">(keys[0] ?? "demo");
  const e = CALIBRATION.engines[eng];
  if (!e) return <div className="card pad small muted">No calibration yet. Run <span className="mono">python calibration.py</span>.</div>;
  const h = e.heldout;
  return (
    <div className="card pad calib">
      <div className="card-head">
        <div>
          <div className="card-title"><Target /> Confidence calibration</div>
          <div className="card-sub">{e.label}: {e.images} images, {e.items.toLocaleString()} judged items with a known answer. Fitted on even images, scored here on the odd ones.</div>
        </div>
        {keys.length > 1 && <Seg value={eng} onChange={setEng} options={keys.map((k) => ({ value: k, label: k === "demo" ? "Synthetic cabinets" : "Real cabinet (renders)" }))} />}
      </div>
      <div className="calib-grid">
        <div className="calib-plot">
          <Diagram e={e} />
          <div className="legend tiny faint">
            <span><i className="calib-sw raw" />raw engine score · ECE {h.ece_raw != null ? `${(h.ece_raw * 100).toFixed(1)}%` : "–"}</span>
            <span><i className="calib-sw cal" />calibrated · ECE {h.ece_cal != null ? `${(h.ece_cal * 100).toFixed(1)}%` : "–"}</span>
          </div>
        </div>
        <div className="stack" style={{ ["--gap" as string]: "14px" }}>
          <div className="calib-kpis">
            <Kpi value={h.items} label="held-out verdicts" color="var(--accent)" note="PASS and FAIL" />
            <Kpi value={(h.accuracy ?? 0) * 100} decimals={1} suffix="%" label="verdicts right" color="var(--pass)" note="against the answer key" />
            <Kpi value={(h.ece_raw ?? 0) * 100} decimals={1} suffix="%" label="error, raw score" color="var(--text-2)" note="expected calibration error" />
            <Kpi value={(h.ece_cal ?? 0) * 100} decimals={1} suffix="%" label="error, calibrated" color="var(--accent-2)" note="what the console shows" />
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Verdict</th><th>Raw score</th><th>Items</th><th>Calibrated</th></tr></thead>
              <tbody>
                {(["PASS", "FAIL", "REVIEW"] as const).flatMap((v) => (e.maps[v] ?? []).map((b, k) => (
                  <tr key={`${v}${b.lo}`}>
                    <td className="small">{k === 0 ? v : ""}</td>
                    <td className="mono tiny">{Math.round(b.lo * 100)}–{Math.round(b.hi * 100)}%</td>
                    <td className="mono tiny muted">{b.n.toLocaleString()}</td>
                    <td className="mono small">{pct(b.p)}<span className="tiny faint"> {v === "REVIEW" ? "faulty" : "right"}</span></td>
                  </tr>
                )))}
              </tbody>
            </table>
          </div>
          <div className="tiny muted">
            PASS and FAIL: chance the verdict is right. REVIEW: chance the item is really faulty
            {e.review.fault_rate != null && <> (on these runs {pct(e.review.fault_rate)} of REVIEW items were)</>}.
            Every inspection shows these calibrated numbers per item and per photo.
          </div>
        </div>
      </div>
    </div>
  );
}
