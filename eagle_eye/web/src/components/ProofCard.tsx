import { AnimatePresence, motion } from "framer-motion";
import { Flip } from "gsap/Flip";
import { ArrowRight, Bot, Camera, FileImage, Layers, Maximize2, ScanLine, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { STATIC, url } from "../lib/api";
import { CHECK_TITLE, COLOUR_HEX, COLOUR_NAME, STATUS_COLOR, STATUS_HEX, explain, statusOf, tone, wireClassPhrase } from "../lib/format";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { gaFor } from "../lib/static";
import type { Item, Pt } from "../lib/types";
import { ConfidenceChip } from "./Confidence";
import { CropView } from "./CropView";
import { WireCode } from "./WireRule";
import { Marker, Meter, Seg, StatusBadge, Switch } from "./ui";

gsap.registerPlugin(Flip);

type CropKind = "expected" | "found" | "aligned";

/** #31 a proof crop expands into the modal: the thumbnail and the modal image share a data-flip-id, so Flip grows one
 *  into the other. The modal shows every crop large, with an X-ray toggle that lays the drawing over the
 *  drawing-aligned photo crop (demo engine, where the two share one coordinate frame). */
function ProofZoom({ run, it, geo, from, state, onClose }: {
  run: string; it: Item; geo?: Geo; from: CropKind; state: Flip.FlipState | null; onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [xray, setXray] = useState(false);
  const real = isReal(it, geo);
  const kinds: CropKind[] = real ? ["expected", "found"] : ["expected", "found", "aligned"];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useGSAP(() => {
    if (calm()) return;
    const el = ref.current!;
    gsap.from(el.querySelector(".pz-back"), { opacity: 0, duration: 0.3 });
    if (state) Flip.from(state, { targets: el.querySelector(`[data-flip-id="crop-${it.id}-${from}"]`), duration: 0.6, ease: "expo.inOut", absolute: true, scale: true, zIndex: 260 });
    gsap.from(el.querySelectorAll(".pz-fig:not(.pz-from), .pz-meta > *"), { opacity: 0, y: 12, stagger: 0.05, delay: 0.25, duration: 0.45 });
  }, { scope: ref });
  const crop = (k: CropKind) => (STATIC && geo ? <StaticCrop run={run} it={it} kind={k} geo={geo} /> : <img src={url.crop(run, it.id, k)} alt={`${k} crop for ${it.id}`} />);
  return createPortal(
    <div className="proof-zoom" ref={ref} role="dialog" aria-label={`Proof for ${it.id}`}>
      <div className="pz-back" onClick={onClose} />
      <div className="pz-card card">
        <div className="row between pz-head">
          <div className="row" style={{ ["--gap" as string]: "10px" }}>
            {it.marker != null && <Marker n={it.marker} s={statusOf(it)} lg />}
            <div>
              <div className="mono proof-id">{it.id}</div>
              <div className="tiny faint">{CHECK_TITLE[it.check] ?? it.check} · {it.target}</div>
            </div>
            <StatusBadge s={statusOf(it)} lg />
          </div>
          <div className="row" style={{ ["--gap" as string]: "10px" }}>
            {!real && <Switch on={xray} onChange={setXray} label="X-ray: drawing over the photo" />}
            <button className="btn btn-icon btn-ghost" onClick={onClose} aria-label="Close"><X /></button>
          </div>
        </div>
        <div className={`pz-grid n${kinds.length}`}>
          {kinds.map((k) => (
            <figure key={k} className={`pz-fig${k === from ? " pz-from" : ""}`}>
              <figcaption>{k === "expected" ? "Expected · GA drawing" : k === "found" ? "Found · photo" : "Aligned to the drawing"}</figcaption>
              <div className={`pz-img${k === "expected" ? " drawing" : ""}`} data-flip-id={`crop-${it.id}-${k}`} style={tone(STATUS_COLOR[statusOf(it)])}>
                {crop(k)}
                {k === "aligned" && xray && <div className="pz-xray">{crop("expected")}</div>}
              </div>
            </figure>
          ))}
        </div>
        <div className="pz-meta">
          <div className="proof-ef">
            <div><div className="tiny faint">Expected (drawing)</div><div className="mono">{it.expected}</div></div>
            <ArrowRight size={16} className="faint" />
            <div><div className="tiny faint">Found (photo)</div><div className="mono" style={{ color: STATUS_COLOR[statusOf(it)] }}>{it.found}</div></div>
          </div>
          <p className="proof-why">{explain(it)}</p>
        </div>
      </div>
    </div>,
    document.body,
  );
}

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
  if (kind !== "expected" && !it.quad.length) return <div className="empty tiny">No reliable photo location for this item</div>;
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
    return <CropView src={g.src} size={[g.w, g.h]} rect={[T(x - m, "x"), T(y - m, "y"), T(x + w + m, "x"), T(y + h + m, "y")]} outline={quad(T)} color="#0a66e8" bg="#fff" />;
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
  const [zoom, setZoom] = useState<{ kind: CropKind; state: Flip.FlipState | null } | null>(null);
  const imgs = useRef<HTMLDivElement>(null);
  const s = statusOf(it);
  const open = (kind: CropKind) => {
    const el = imgs.current?.querySelector(`[data-flip-id="crop-${it.id}-${kind}"]`);
    setZoom({ kind, state: el && !calm() ? Flip.getState(el) : null });
  };
  // #32 proof layer wipe: the photo crop wipes in over its frame each time an item opens
  useGSAP(() => {
    if (calm() || !imgs.current) return;
    const photo = imgs.current.querySelector(".proof-img:not(.drawing) > *");
    const drawing = imgs.current.querySelector(".proof-img.drawing > *");
    gsap.fromTo(photo, { clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)", duration: 0.5, ease: "power2.inOut", delay: 0.15, clearProps: "clipPath" });
    gsap.fromTo(drawing, { opacity: 0 }, { opacity: 1, duration: 0.35, clearProps: "opacity" });
  }, { dependencies: [it.id, found] });
  const isPass = it.result === "PASS" && !it.recheck;
  const real = isReal(it, geo);
  if (it.check === "REGISTRATION" || it.id === "REG-DRAWING") return <div className="proof">
    <div className="row between"><div className="mono proof-id">{it.id}</div><StatusBadge s="REVIEW" /></div>
    <h3>Check the photograph and drawing</h3>
    <p className="proof-why">{explain(it)}</p>
    <div className="callout warn" style={{ margin: 0 }}><Camera /><span className="small">Use the exact cabinet's drawing and revision. Capture the relevant backplate view with readable labels; retaking the photo cannot correct an unrelated drawing.</span></div>
  </div>;
  return (
    <AnimatePresence mode="wait">
      <motion.div key={it.id} className="proof" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.28 }}>
        <div className="row between proof-head">
          <div className="row" style={{ ["--gap" as string]: "11px" }}>
            {it.marker != null ? <Marker n={it.marker} s={s} lg /> : <span className="proof-dot" style={tone(STATUS_COLOR[s])} />}
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

        <div className="proof-imgs" ref={imgs}>
          <figure>
            <figcaption><FileImage size={13} /> Expected · GA drawing</figcaption>
            <div className="proof-img drawing zoomable" data-flip-id={`crop-${it.id}-expected`} role="button" tabIndex={0} title="Open the proof large"
              onClick={() => open("expected")} onKeyDown={(e) => e.key === "Enter" && open("expected")}>
              <span className="zoom-hint"><Maximize2 size={12} /></span>
              {STATIC && geo ? <StaticCrop run={run} it={it} kind="expected" geo={geo} /> : <img src={url.crop(run, it.id, "expected")} alt={`Drawing crop for ${it.id}`} />}
            </div>
          </figure>
          <figure>
            <figcaption className="row between">
              <span className="row" style={{ ["--gap" as string]: "6px" }}><ScanLine size={13} /> Found · photo</span>
              {!real && <Seg value={found} onChange={setFound} options={[{ value: "found", label: "Photo", title: "Zoomed crop of the original photo" }, { value: "aligned", label: <><Layers size={12} />Aligned</>, title: "Perspective-corrected, pixel-aligned with the drawing" }]} />}
            </figcaption>
            <div className="proof-img zoomable" data-flip-id={`crop-${it.id}-${real ? "found" : found}`} style={tone(STATUS_COLOR[s])} role="button" tabIndex={0} title="Open the proof large"
              onClick={() => open(real ? "found" : found)} onKeyDown={(e) => e.key === "Enter" && open(real ? "found" : found)}>
              <span className="zoom-hint"><Maximize2 size={12} /></span>
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
        {it.check === "COLOUR" && it.colour && (
          <div className="stack" style={{ ["--gap" as string]: "8px" }}>
            <div className="row wrap" style={{ ["--gap" as string]: "18px" }}>
              <div>
                <div className="tiny faint">Allowed for {it.wire_class ? wireClassPhrase(it.wire_class) : "this wire"}</div>
                <div className="row wrap" style={{ ["--gap" as string]: "5px", marginTop: 4 }}>
                  {(it.allowed ?? []).map((c) => <WireCode key={c} c={c} />)}
                  {!(it.allowed ?? []).length && <span className="tiny">anything but green-and-yellow</span>}
                </div>
              </div>
              <Swatch code={it.colour} hex={it.swatch} label="Measured after white balance" />
            </div>
            <div className="tiny faint">Rule: {it.rule_source ?? "universal (green-and-yellow for protective earth only)"}</div>
          </div>
        )}
        {it.check === "COLOUR" && !it.colour && it.id.startsWith("COL-") && (
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
              <b>Recorded verifier {it.agent.model ? `(${it.agent.model})` : ""}: {it.agent.decision.replace("_", " ").toLowerCase()}</b>
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
          <ConfidenceChip it={it} eng={isReal(it, geo) ? "real" : "demo"} wide />
        </div>
        {zoom && <ProofZoom run={run} it={it} geo={geo} from={zoom.kind} state={zoom.state} onClose={() => setZoom(null)} />}
      </motion.div>
    </AnimatePresence>
  );
}
