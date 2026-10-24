/** Cross-cabinet fault Pareto: recurring FAILs ranked by fault, device family, cabinet area or line station, with their
 *  cumulative share, so QC findings go back to the station that causes them. Picking a row focuses the heatmap. */
import { Factory } from "lucide-react";
import { useMemo } from "react";
import { checkOfId, pareto, type ParetoBy, type ParetoRow } from "../lib/assembly";
import { CHECK_TITLE } from "../lib/format";
import type { RunMeta, RunPayload } from "../lib/types";
import { Seg } from "./ui";

const BY: { value: ParetoBy; label: string }[] = [
  { value: "fault", label: "Fault" }, { value: "family", label: "Device family" },
  { value: "area", label: "Cabinet area" }, { value: "station", label: "Line station" },
];
const W = 520;
const H = 230;
const M = { l: 34, r: 40, t: 14, b: 30 };

function Chart({ rows, focus, onFocus }: { rows: ParetoRow[]; focus: string | null; onFocus: (r: ParetoRow) => void }) {
  // the y axis follows the ranked rows; a taller "Other" bar is capped with a break mark and keeps its true count
  const max = Math.max(1, ...rows.filter((r) => r.key !== "__other").map((r) => r.n));
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;
  const step = iw / Math.max(1, rows.length);
  const bw = Math.min(56, step * 0.62);
  const x = (k: number) => M.l + step * k + step / 2;
  const yN = (n: number) => M.t + ih - (n / max) * ih;
  const yP = (p: number) => M.t + ih - p * ih;
  const line = rows.map((r, k) => `${k ? "L" : "M"}${x(k).toFixed(1)},${yP(r.cum).toFixed(1)}`).join(" ");
  const ticks = [...new Set([0, Math.round(max / 2), max])];
  return (
    <svg className="pareto-chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Pareto of recurring FAILs: ${rows.map((r) => `${r.label} ${r.n}`).join(", ")}`}>
      {ticks.map((t) => (
        <g key={t}>
          <line className="pareto-grid" x1={M.l} x2={W - M.r} y1={yN(t)} y2={yN(t)} />
          <text className="pareto-axis" x={M.l - 6} y={yN(t) + 4} textAnchor="end">{t}</text>
        </g>
      ))}
      {[0.5, 1].map((p) => <text key={p} className="pareto-axis" x={W - M.r + 6} y={yP(p) + 4}>{p * 100}%</text>)}
      <line className="pareto-80" x1={M.l} x2={W - M.r} y1={yP(0.8)} y2={yP(0.8)} />
      <text className="pareto-axis" x={W - M.r + 6} y={yP(0.8) + 4}>80%</text>
      {rows.map((r, k) => (
        <g key={r.key} className={`pareto-bar${focus === r.key ? " on" : ""}${r.key === "__other" ? " other" : ""}`} onClick={() => r.key !== "__other" && onFocus(r)}>
          <rect x={x(k) - bw / 2} y={yN(Math.min(r.n, max))} width={bw} height={Math.max(1, M.t + ih - yN(Math.min(r.n, max)))} rx={4} />
          {r.n > max && <path className="pareto-break" d={`M${x(k) - bw / 2 - 3},${yN(max) + 14} l${bw + 6},-6 m0,7 l${-bw - 6},6`} />}
          <text className="pareto-n" x={x(k)} y={yN(Math.min(r.n, max)) - 5} textAnchor="middle">{r.n}</text>
          <text className="pareto-axis" x={x(k)} y={H - M.b + 16} textAnchor="middle">{r.key === "__other" ? "Other" : `#${k + 1}`}</text>
        </g>
      ))}
      <path className="pareto-cum" d={line} />
      {rows.map((r, k) => <circle key={r.key} className="pareto-dot" cx={x(k)} cy={yP(r.cum)} r={3.5} />)}
    </svg>
  );
}

export function FaultPareto({ metas, base, by, onBy, focus, onFocus }: {
  metas: RunMeta[]; base: RunPayload | null; by: ParetoBy; onBy: (b: ParetoBy) => void;
  focus: string | null; onFocus: (row: ParetoRow | null) => void;
}) {
  const { rows, total } = useMemo(() => pareto(metas, by, base), [metas, by, base]);
  const head = rows.filter((r) => r.key !== "__other");
  const top = head[0];
  const pick = (r: ParetoRow) => onFocus(focus === r.key ? null : r);
  return (
    <div className="card pad pareto">
      <div className="card-head">
        <div>
          <div className="card-title"><Factory /> Fault Pareto: send it back to the line</div>
          <div className="card-sub">
            {total ? <>Recurring FAILs across {metas.length} runs, ranked. {top && <>#1 <b>{top.label}</b> alone is {Math.round(top.share * 100)}% of all {total} FAILs; the top {head.length} make {Math.round((head[head.length - 1]?.cum ?? 0) * 100)}%.</>} Pick a row to see it on the heatmap.</>
              : "No FAILs in this selection."}
          </div>
        </div>
        <Seg value={by} onChange={(b) => { onBy(b); onFocus(null); }} options={BY} />
      </div>
      {total > 0 && (
        <div className="pareto-grid-2">
          <Chart rows={rows} focus={focus} onFocus={pick} />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{BY.find((b) => b.value === by)!.label}</th>
                  {by === "fault" ? <><th>Device family</th><th>Cabinet area</th><th>Line station</th></> : <th>Most frequent items</th>}
                  <th>FAIL</th>
                  <th>Cum.</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, k) => (
                  <tr key={r.key} aria-selected={focus === r.key} onClick={() => r.key !== "__other" && pick(r)} className={r.key === "__other" ? "pareto-other" : ""}>
                    <td className="mono small faint">{r.key === "__other" ? "" : k + 1}</td>
                    <td className={by === "fault" ? "mono small" : "small"}>{r.label}{by === "fault" && r.key !== "__other" && <div className="tiny faint">{CHECK_TITLE[checkOfId(r.key)] ?? checkOfId(r.key)}</div>}</td>
                    {by === "fault"
                      ? <><td className="small">{r.family ?? ""}</td><td className="small">{r.area ?? ""}</td><td className="small muted">{r.station ?? ""}</td></>
                      : <td className="mono tiny muted">{(r.top ?? []).join(", ")}</td>}
                    <td className="mono small">{r.n}<span className="tiny faint"> · {Math.round(r.share * 100)}%</span></td>
                    <td className="mono small">{Math.round(r.cum * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
