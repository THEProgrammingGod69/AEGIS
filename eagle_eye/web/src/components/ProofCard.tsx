import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, FileImage, Layers, ScanLine } from "lucide-react";
import { useState } from "react";
import { url } from "../lib/api";
import { CHECK_TITLE, COLOUR_HEX, COLOUR_NAME, STATUS_COLOR, explain, statusOf } from "../lib/format";
import type { Item } from "../lib/types";
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

export function ProofCard({ run, it }: { run: string; it: Item }) {
  const [found, setFound] = useState<"found" | "aligned">("found");
  const s = statusOf(it);
  const isPass = it.result === "PASS" && !it.recheck;
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
              <img src={url.crop(run, it.id, "expected")} alt={`Drawing crop for ${it.id}`} />
            </div>
          </figure>
          <figure>
            <figcaption className="row between">
              <span className="row" style={{ ["--gap" as string]: "6px" }}><ScanLine size={13} /> Found · photo</span>
              <Seg value={found} onChange={setFound} options={[{ value: "found", label: "Photo", title: "Zoomed crop of the original photo" }, { value: "aligned", label: <><Layers size={12} />Aligned</>, title: "Perspective-corrected, pixel-aligned with the drawing" }]} />
            </figcaption>
            <div className="proof-img" style={{ ["--c" as string]: STATUS_COLOR[s] }}>
              <img key={found} src={url.crop(run, it.id, found)} alt={`Photo crop for ${it.id}`} />
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
