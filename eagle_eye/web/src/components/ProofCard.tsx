import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Bot, Camera, FileImage, Layers, ScanLine } from "lucide-react";
import { useState } from "react";
import { STATIC, url } from "../lib/api";
import { CHECK_TITLE, COLOUR_HEX, COLOUR_NAME, STATUS_COLOR, STATUS_HEX, explain, statusOf } from "../lib/format";
import { gaFor } from "../lib/static";
import type { Item, Pt } from "../lib/types";
import { CropView } from "./CropView";
import { Marker, Meter, Seg, StatusBadge } from "./ui";

function RailDiagram({ it }: { it: Item }) {
  const swapped = new Set((it.swaps ?? []).flat());
  return (
    <div className="rail">
      {(["expected", "read"] as const).map((row) => (
        <div key={row} className="rail-row">
          <span className="rail-label">{row === "expected" ? "Drawing" : "Read on rail"}</span>
          <div className="rail-slots">
            {it.slots!.map((s) => {
              const v = row === "expected" ? s.expected : s.read;
              const bad = row === "read" && v !== s.expected;
              return (
                <span key={s.slot} className={`rail-slot${bad ? " bad" : ""}${row === "expected" && swapped.has(s.expected) ? " hl" : ""}`}>
                  <i>{s.slot}</i>
                  {v}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function Swatch({ code, hex, label }: { code: string; hex?: string; label: string }) {
  return (
    <div className="swatch">
      <span className="swatch-chip" style={{ background: hex ?? COLOUR_HEX[code] ?? "#333" }} />
      <div>
        <div className="tiny faint">{label}</div>
        <div className="mono small">{COLOUR_NAME[code] ?? code} <span className="faint">({code})</span></div>
      </div>
    </div>
  );
}

export interface Geo {
  photoSize: [number, number];
  sizeMm: [number, number];
  /** real-cabinet run: photo-pixel boxes, drawing crops per item, no drawing-aligned view */
  real?: boolean;
}

const isReal = (it: Item, geo?: Geo) => geo?.real ?? it.verified_by !== undefined;

/** Proof crop built in the browser (hosted showcase): same windows as report.py's expected/found/aligned crops. */
function StaticCrop({ run, it, kind, geo }: { run: string; it: Item; kind: "expected" | "found" | "aligned"; geo: Geo }) {
  const [x, y, w, h] = it.box;
  const m = 15;
  const quad = (f: (v: number, a: "x" | "y") => number): Pt[] => [[f(x, "x"), f(y, "y")], [f(x + w, "x"), f(y, "y")], [f(x + w, "x"), f(y + h, "y")], [f(x, "x"), f(y + h, "y")]];
  if (kind === "expected" && isReal(it, geo)) {
    const src = url.file(run, `exp:${it.id}`);
    return src ? <img src={src} alt={`Drawing crop for ${it.id}`} style={{ width: "100%", height: "100%", objectFit: "contain", background: "#fff" }} />
      : <div className="empty tiny">No drawing crop kept for this item</div>;
  }
  if (kind === "expected") {
    const g = gaFor(run);
    const T = (v: number, a: "x" | "y") => (a === "x" ? g.ox : g.oy) + v * g.k;
    return <CropView src={g.src} size={[g.w, g.h]} rect={[T(x - m, "x"), T(y - m, "y"), T(x + w + m, "x"), T(y + h + m, "y")]} outline={quad(T)} color="#0ea5e9" bg="#fff" />;
  }
  if (kind === "aligned") {
    const T = (v: number) => v * 4;
    return <CropView src={url.file(run, "rectified")} size={[geo.sizeMm[0] * 4, geo.sizeMm[1] * 4]} rect={[T(x - m), T(y - m), T(x + w + m), T(y + h + m)]} outline={quad(T)} color={STATUS_HEX[statusOf(it)]} />;
  }
  const xs = it.quad.map((p) => p[0]);
  const ys = it.quad.map((p) => p[1]);
  return <CropView src={url.file(run, "photo")} size={geo.photoSize} rect={[Math.min(...xs) - 60, Math.min(...ys) - 60, Math.max(...xs) + 60, Math.max(...ys) + 60]} outline={it.quad} color={STATUS_HEX[statusOf(it)]} />;
}

/** One proof image (drawing / photo / aligned) for an item: built in the browser on the hosted console, served by the local engine. */
export function ProofCrop({ run, it, kind, geo }: { run: string; it: Item; kind: "expected" | "found" | "aligned"; geo: Geo }) {
  return STATIC ? <StaticCrop run={run} it={it} kind={kind} geo={geo} /> : <img src={url.crop(run, it.id, kind)} alt={`${kind} crop for ${it.id}`} />;
}

export function ProofCard({ run, it, geo }: { run: string; it: Item; geo?: Geo }) {
  const [found, setFound] = useState<"found" | "aligned">("found");
  const s = statusOf(it);
  const isPass = it.result === "PASS" && !it.recheck;
  const real = isReal(it, geo);
  return (
    <AnimatePresence mode="wait">
      <motion.div key={it.id} className="proof" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.28 }}>
        <div className="row between proof-head">
          <div className="row" style={{ ["--gap" as string]: "11px" }}>
            {it.marker != null ? <Marker n={it.marker} s={s} lg /> : <span className="proof-dot" style={{ ["--c" as string]: STATUS_COLOR[s] }} />}
            <div style={{ minWidth: 0 }}>
              <div className="mono proof-id">{it.id}</div>
              <div className="tiny faint">{CHECK_TITLE[it.check] ?? it.check} · {it.target}</div>
            </div>
          </div>
          <div className="row" style={{ ["--gap" as string]: "6px" }}>
            {it.recheck && <StatusBadge s={it.recheck} lg />}
            <StatusBadge s={it.result} lg={!it.recheck} />
          </div>
        </div>

        <div className="proof-imgs">
          <figure>
            <figcaption><FileImage size={13} /> Expected · GA drawing</figcaption>
            <div className="proof-img drawing">
              {STATIC && geo ? <StaticCrop run={run} it={it} kind="expected" geo={geo} /> : <img src={url.crop(run, it.id, "expected")} alt={`Drawing crop for ${it.id}`} />}
            </div>
          </figure>
          <figure>
            <figcaption className="row between">
              <span className="row" style={{ ["--gap" as string]: "6px" }}><ScanLine size={13} /> Found · photo</span>
              {!real && <Seg value={found} onChange={setFound} options={[{ value: "found", label: "Photo", title: "Zoomed crop of the original photo" }, { value: "aligned", label: <><Layers size={12} />Aligned</>, title: "Perspective-corrected, pixel-aligned with the drawing" }]} />}
            </figcaption>
            <div className="proof-img" style={{ ["--c" as string]: STATUS_COLOR[s] }}>
              {STATIC && geo ? <StaticCrop key={found} run={run} it={it} kind={real ? "found" : found} geo={geo} /> : <img key={found} src={url.crop(run, it.id, real ? "found" : found)} alt={`Photo crop for ${it.id}`} />}
            </div>
          </figure>
        </div>

        <div className="proof-ef">
          <div>
            <div className="tiny faint">Expected (drawing)</div>
            <div className="mono">{it.expected}</div>
          </div>
          <ArrowRight size={16} className="faint" />
          <div>
            <div className="tiny faint">Found (photo)</div>
            <div className="mono" style={{ color: isPass ? "var(--text)" : STATUS_COLOR[s] }}>{it.found}</div>
          </div>
        </div>

        {it.slots && <RailDiagram it={it} />}
        {it.check === "COLOUR" && (
          <div className="row wrap" style={{ ["--gap" as string]: "18px" }}>
            <Swatch code={it.expected} label="Wire list says" />
            <Swatch code={it.found} hex={it.swatch} label="Measured after white balance" />
          </div>
        )}
        {it.votes && it.votes.length > 0 && (
          <div>
            <div className="tiny faint" style={{ marginBottom: 6 }}>OCR votes (decoded against the closed vocabulary)</div>
            <div className="row wrap" style={{ ["--gap" as string]: "6px" }}>
              {it.votes.map((v, i) => <span key={i} className="tag">{v || "∅"}</span>)}
            </div>
          </div>
        )}
        {it.occupancy != null && it.check === "GA" && (
          <div>
            <div className="row between tiny faint" style={{ marginBottom: 6 }}>
              <span>Slot occupancy vs empty-backplate model</span>
              <span className="mono">{Math.round(it.occupancy * 100)}%</span>
            </div>
            <Meter value={it.occupancy} color={STATUS_COLOR[it.result]} />
          </div>
        )}

        {real && it.agent && (
          <div className="callout info" style={{ margin: 0 }}>
            <Bot />
            <span className="small">
              <b>Claude {it.agent.model ? `(${it.agent.model})` : ""}: {it.agent.decision.replace("_", " ").toLowerCase()}</b>
              {" "}· {Math.round(it.agent.confidence * 100)}%{it.agent.cached ? " · cached" : ""} — {it.agent.reason}
            </span>
          </div>
        )}
        {real && it.result === "REVIEW" && it.hint && (
          <div className="callout warn" style={{ margin: 0 }}><Camera /><span className="small">Re-photo: {it.hint}</span></div>
        )}
        <p className="proof-why">{explain(it)}</p>
        {it.prev_result && (
          <div className="proof-before">
            <span className="faint">Before re-check:</span> <StatusBadge s={it.prev_result} /> <span className="mono small">{it.prev_found}</span>
          </div>
        )}
        <div className="row between tiny faint">
          <span className="mono ellipsis" title={it.evidence.join("; ")}>{it.evidence.join(" · ")}</span>
          <span className="nowrap">conf {Math.round(it.conf * 100)}%</span>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
