/** Photos taken at an angle (eagle_eye/eval_angle.py): renders of the real cabinet's GA views seen through a virtual
 *  camera turned sideways, inspected with the flat registration alone and with the perspective search. Shows how many
 *  of the labels read still land on the drawing, what the engine verified, and the camera angle it measured. */
import { Compass } from "lucide-react";
import { useRef } from "react";
import SWEEP from "../data/angle_sweep.json";
import { useChartIn } from "./motion";
import { Kpi } from "./ui";

interface Row {
  angle: number; mode: "flat" | "perspective"; images: number; localised: number; inliers: number; anchors: number;
  pass: number; fail: number; review: number; not_in_view: number; verified: number; perspective_fits: number;
  measured_mean: number | null; measured_error: number | null;
}
interface Sweep { created: string; engine_version: string; views: number; note: string; angles: number[]; rows: Row[] }

const DATA = SWEEP as unknown as Sweep;
const S = { w: 520, h: 250 };
const M = { l: 46, r: 16, t: 16, b: 40 };
const share = (r?: Row) => (r && r.anchors ? r.inliers / r.anchors : 0);

function Chart({ rows }: { rows: Row[] }) {
  const angles = DATA.angles;
  const iw = S.w - M.l - M.r;
  const ih = S.h - M.t - M.b;
  const lo = Math.min(...angles), hi = Math.max(...angles);
  const x = (a: number) => M.l + ((a - lo) / Math.max(1, hi - lo)) * iw;
  const y = (v: number) => M.t + ih - v * ih;
  const line = (mode: Row["mode"]) => angles.map((a, k) => {
    const r = rows.find((q) => q.angle === a && q.mode === mode);
    return `${k ? "L" : "M"}${x(a).toFixed(1)},${y(share(r)).toFixed(1)}`;
  }).join(" ");
  return (
    <svg className="calib-chart" viewBox={`0 0 ${S.w} ${S.h}`} role="img" aria-label="Share of read labels placed on the drawing against the camera angle">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line className="calib-gridline" x1={M.l} x2={M.l + iw} y1={y(t)} y2={y(t)} />
          <text className="calib-axis" x={M.l - 6} y={y(t) + 4} textAnchor="end">{Math.round(t * 100)}</text>
        </g>
      ))}
      {angles.map((a) => <text key={a} className="calib-axis" x={x(a)} y={M.t + ih + 16} textAnchor="middle">{a}°</text>)}
      <path className="calib-raw" d={line("flat")} data-draw-line="" />
      <path className="calib-cal" d={line("perspective")} data-draw-line="" />
      {rows.map((r) => (
        <circle key={`${r.mode}${r.angle}`} data-pop="" className={r.mode === "flat" ? "calib-raw-dot" : "calib-cal-dot"} cx={x(r.angle)} cy={y(share(r))} r={4.5}>
          <title>{`${r.mode === "flat" ? "Flat registration" : "With the perspective search"} at ${r.angle}°: ${r.inliers} of ${r.anchors} read labels placed (${Math.round(share(r) * 100)}%)`}</title>
        </circle>
      ))}
      <text className="calib-label" x={M.l + iw / 2} y={S.h - 6} textAnchor="middle">Camera turned sideways (degrees)</text>
      <text className="calib-label" x={12} y={M.t + ih / 2} textAnchor="middle" transform={`rotate(-90 12 ${M.t + ih / 2})`}>Read labels placed (%)</text>
    </svg>
  );
}

export function AnglePanel() {
  const rows = DATA.rows ?? [];
  const chart = useRef<HTMLDivElement>(null);
  useChartIn(chart);
  if (!rows.length) return <div className="card pad small muted">No angle sweep yet. Run <span className="mono">python eval_angle.py</span>.</div>;
  const top = Math.max(...DATA.angles);
  const at = (a: number, m: Row["mode"]) => rows.find((r) => r.angle === a && r.mode === m);
  const flat = at(top, "flat"), per = at(top, "perspective");
  const err = rows.filter((r) => r.mode === "perspective" && r.angle > 0 && r.measured_error != null);
  const meanErr = err.length ? err.reduce((s, r) => s + (r.measured_error ?? 0), 0) / err.length : null;
  const falseFails = rows.filter((r) => r.mode === "perspective").reduce((s, r) => s + r.fail, 0);
  return (
    <div className="card pad calib" ref={chart}>
      <div className="card-head">
        <div>
          <div className="card-title"><Compass /> Photos taken from the side</div>
          <div className="card-sub">{DATA.views} GA views of the real cabinet, each seen from {DATA.angles.filter((a) => a > 0).map((a) => `±${a}°`).join(", ")} and straight on, inspected twice: flat registration alone, and with the perspective search.</div>
        </div>
      </div>
      <div className="calib-grid">
        <div className="calib-plot">
          <Chart rows={rows} />
          <div className="legend tiny faint">
            <span><i className="calib-sw raw" />flat registration</span>
            <span><i className="calib-sw cal" />with the perspective search</span>
          </div>
        </div>
        <div className="stack" style={{ ["--gap" as string]: "14px" }}>
          <div className="calib-kpis">
            <Kpi value={share(per) * 100} suffix="%" label={`labels placed at ${top}°`} color="var(--accent-2)" note={`flat registration: ${Math.round(share(flat) * 100)}%`} />
            <Kpi value={per?.pass ?? 0} label={`labels verified at ${top}°`} color="var(--pass)" note={`flat registration: ${flat?.pass ?? 0}`} />
            <Kpi value={meanErr ?? 0} decimals={1} suffix="°" label="angle error" color="var(--accent)" note="measured against the true turn" />
            <Kpi value={falseFails} label="false FAILs" color={falseFails ? "var(--fail)" : "var(--text-2)"} note="no fault is planted here" />
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Angle</th><th>Labels placed</th><th>PASS</th><th>REVIEW</th><th>Measured</th></tr></thead>
              <tbody>
                {DATA.angles.map((a) => {
                  const f = at(a, "flat"), q = at(a, "perspective");
                  return (
                    <tr key={a}>
                      <td className="mono small">{a}°</td>
                      <td className="mono tiny">{f?.inliers ?? 0} → <b>{q?.inliers ?? 0}</b> <span className="faint">of {q?.anchors ?? 0}</span></td>
                      <td className="mono tiny">{f?.pass ?? 0} → {q?.pass ?? 0}</td>
                      <td className="mono tiny">{f?.review ?? 0} → {q?.review ?? 0}</td>
                      <td className="mono tiny">{q?.measured_mean != null ? `${q.measured_mean}°` : "straight"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="tiny muted">
            A photo from the side is not a scaled copy of the drawing: the far side shrinks and rails converge. The engine
            searches the perspective when the flat fit leaves labels unexplained, lays the drawing on at that angle, measures
            the angle and can show the photo straightened.
          </div>
        </div>
      </div>
      <div className="tiny faint">{DATA.note}. Engine {DATA.engine_version}, {new Date(DATA.created).toLocaleDateString()}.</div>
    </div>
  );
}
