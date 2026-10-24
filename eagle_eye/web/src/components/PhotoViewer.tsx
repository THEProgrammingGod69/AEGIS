import { Maximize2, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { STATUS_HEX } from "../lib/format";
import { calm, gsap, useGSAP } from "../lib/gsap";
import { onXray, xrayOn } from "../lib/interactions";
import { useSize } from "../lib/hooks";
import { polygonBounds } from "../lib/geometry";
import type { Pt, Status } from "../lib/types";

export interface ViewerItem {
  id: string;
  quad: Pt[];
  status: Status;
  marker?: number | null;
  caption?: string;
}

export interface ViewerAnchor {
  tag: string;
  found: Pt;
  expected: Pt;
  inlier: boolean | null;
}

export interface ViewerLayers {
  issues: boolean;
  drawing: boolean;
  anchors: boolean;
}

interface Props {
  src: string;
  size: [number, number];
  items?: ViewerItem[];
  layout?: { tag: string; kind: string; quad: Pt[] }[];
  anchors?: ViewerAnchor[];
  backplate?: Pt[];
  layers?: ViewerLayers;
  overlaySrc?: string;
  overlayOpacity?: number;
  selected?: string | null;
  selectedQuad?: Pt[] | null;
  hovered?: string | null;
  onSelect?: (id: string) => void;
  onHover?: (id: string | null) => void;
  scanning?: boolean;
  /** Bump to zoom onto the selected item (user-driven selection); the initial view always shows the whole photo. */
  focusKey?: number;
  height?: number | string;
  children?: ReactNode;
  interactive?: boolean;
}

/** Text label on a dark chip, sized in screen pixels whatever the zoom (u = overlay units per pixel). */
function Chip({ x, y, u, color, text, small }: { x: number; y: number; u: number; color: string; text: string; small?: boolean }) {
  const fs = (small ? 10.5 : 12) * u;
  const w = text.length * fs * 0.62 + 14 * u;
  const h = fs * 1.75;
  return (
    <g pointerEvents="none">
      <rect x={x} y={y} width={w} height={h} rx={6 * u} fill="rgba(5,7,11,0.88)" stroke={color} strokeOpacity={0.55} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <text x={x + 7 * u} y={y + h * 0.69} fontSize={fs} className="svg-chip" style={{ fill: color }}>{text}</text>
    </g>
  );
}

export function PhotoViewer({
  src, size, items = [], layout = [], anchors = [], backplate, layers = { issues: true, drawing: false, anchors: false },
  overlaySrc, overlayOpacity = 0.6, selected, selectedQuad, hovered, onSelect, onHover, scanning, focusKey = 0,
  height = "min(78vh, 860px)", children, interactive = true,
}: Props) {
  const [W, H] = size;
  const [ref, box] = useSize<HTMLDivElement>();
  // Bonus X-ray mode (press X): every photo shows its GA overlay
  const [xray, setXray] = useState(() => xrayOn());
  useEffect(() => onXray(setXray), []);
  const show = { ...layers, drawing: layers.drawing || (xray && layout.length > 0) };
  const [view, setView] = useState({ s: 0, x: 0, y: 0 });
  const [anim, setAnim] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);

  const fit = useMemo(() => {
    if (!box.w || !box.h) return { s: 0, x: 0, y: 0 };
    const s = Math.min(box.w / W, box.h / H) * 0.94;
    return { s, x: (box.w - W * s) / 2, y: (box.h - H * s) / 2 };
  }, [box.w, box.h, W, H]);

  // re-fit when the viewer or the coordinate space changes size
  useLayoutEffect(() => {
    if (fit.s) {
      setAnim(false);
      setView(fit);
    }
  }, [fit]);

  useEffect(() => setLoaded(false), [src]);

  const focusQuad = selectedQuad ?? items.find((i) => i.id === selected)?.quad ?? null;
  useEffect(() => {
    if (!focusKey || !focusQuad || !fit.s) return;
    const b = polygonBounds(focusQuad);
    if (!b) return;
    const bw = Math.max(b.x1 - b.x0, W * 0.04);
    const bh = Math.max(b.y1 - b.y0, H * 0.03);
    const s = Math.max(fit.s * 1.15, Math.min(fit.s * 5, Math.min(box.w / (bw * 3.6), box.h / (bh * 3.6))));
    const cx = (b.x0 + b.x1) / 2;
    const cy = (b.y0 + b.y1) / 2;
    setAnim(true);
    setView({ s, x: box.w / 2 - cx * s, y: box.h / 2 - cy * s });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey]);

  const zoomAt = useCallback((k: number, mx: number, my: number, animate = false) => {
    setAnim(animate);
    setView((v) => {
      const s = Math.max(fit.s * 0.7, Math.min(fit.s * 14, v.s * k));
      const r = s / v.s;
      return { s, x: mx - (mx - v.x) * r, y: my - (my - v.y) * r };
    });
  }, [fit.s]);

  useEffect(() => {
    const el = ref.current;
    if (!el || !interactive) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0016), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt, ref, interactive]);

  const onDown = (e: React.PointerEvent) => {
    if (!interactive || e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) > 4) {
      d.moved = true;
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    }
    if (d.moved) {
      setAnim(false);
      setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
    }
  };
  const onUp = () => {
    setTimeout(() => (drag.current = null), 0);
  };
  const click = (id: string) => {
    if (drag.current?.moved) return;
    onSelect?.(id);
  };

  // #3 / #32: the GA boxes draw themselves when the drawing layer opens; anchor rings draw and off-pattern anchors pulse
  useGSAP(() => {
    if (calm() || !view.s) return;
    if (show.drawing) gsap.from(".layer-drawing polygon", { drawSVG: 0, duration: 0.7, stagger: 0.02, ease: "power2.out" });
    if (show.anchors) {
      gsap.from(".pv-ring", { drawSVG: 0, duration: 0.4, stagger: 0.02 });
      gsap.to(".pv-ring.off", { scale: 1.25, transformOrigin: "50% 50%", repeat: 3, yoyo: true, duration: 0.18, delay: 0.3 });
    }
  }, { scope: ref, dependencies: [show.drawing, show.anchors, view.s > 0] });

  const u = view.s ? 1 / view.s : 1; // overlay units per screen pixel
  const zoomPct = fit.s ? Math.round((view.s / fit.s) * 100) : 100;

  return (
    <div
      ref={ref}
      className={`viewer${interactive ? " interactive" : ""}${drag.current?.moved ? " dragging" : ""}`}
      style={{ height }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerLeave={onUp}
      onDoubleClick={() => {
        setAnim(true);
        setView(fit);
      }}
    >
      {!loaded && <div className="viewer-loading skeleton" />}
      {view.s > 0 && (
        <div
          className="viewer-stage"
          style={{
            width: W,
            height: H,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`,
            transition: anim ? "transform 0.75s cubic-bezier(0.22, 1, 0.36, 1)" : "none",
          }}
        >
          <img src={src} width={W} height={H} draggable={false} alt="" onLoad={() => setLoaded(true)} style={{ opacity: loaded ? 1 : 0 }} />
          {overlaySrc && <img className="viewer-overlay" src={overlaySrc} width={W} height={H} draggable={false} alt="" style={{ opacity: overlayOpacity }} />}
          <svg className="viewer-svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
            {backplate && polygonBounds(backplate) && (show.drawing || show.anchors) && (
              <polygon points={backplate.map((p) => p.join(",")).join(" ")} fill="none" stroke="#5be3ff" strokeWidth={1.4} strokeDasharray="8 6" vectorEffect="non-scaling-stroke" opacity={0.75} />
            )}
            {show.drawing && (
              <g className="layer-drawing">
                {layout.map((l, i) => {
                  const b = polygonBounds(l.quad);
                  if (!b) return null;
                  return (
                    <g key={l.tag} style={{ animationDelay: `${i * 35}ms` }}>
                      <polygon points={l.quad.map((p) => p.join(",")).join(" ")} fill="rgba(91,227,255,0.05)" stroke="#5be3ff" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
                      {l.kind !== "terminal" && (
                        <text x={b.x0 + 4 * u} y={b.y1 - 6 * u} fontSize={10.5 * u} strokeWidth={2 * u} className="svg-tag">
                          {l.tag}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            )}
            {layers.anchors &&
              anchors.map((a, i) => {
                const c = a.inlier === false ? "#ff5468" : "#2bd49a";
                return (
                  <g key={a.tag + a.found.join()}>
                    {a.inlier === false && (
                      <line x1={a.found[0]} y1={a.found[1]} x2={a.expected[0]} y2={a.expected[1]} stroke={c} strokeWidth={1.5} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
                    )}
                    <circle className={`pv-ring${a.inlier === false ? " off" : ""}`} cx={a.expected[0]} cy={a.expected[1]} r={7 * u} fill="none" stroke="#5be3ff" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.8} />
                    <circle cx={a.found[0]} cy={a.found[1]} r={3.6 * u} fill={c} stroke="#040b15" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                    {a.inlier === false && <Chip x={a.found[0] - 18 * u} y={a.found[1] - (i % 2 ? 44 : 26) * u} u={u} color={c} text={a.tag} small />}
                  </g>
                );
              })}
            {selectedQuad && polygonBounds(selectedQuad) && !items.some((i) => i.id === selected) && (
              <polygon points={selectedQuad.map((p) => p.join(",")).join(" ")} fill="rgba(91,227,255,0.14)" stroke="#7fe7ff" strokeWidth={3} vectorEffect="non-scaling-stroke" className="sel-glow" />
            )}
            {layers.issues &&
              items.map((it) => {
                const b = polygonBounds(it.quad);
                if (!b) return null;
                const c = STATUS_HEX[it.status];
                const on = it.id === selected || it.id === hovered;
                const pad = 6 * u;
                return (
                  <g key={it.id} className={`issue${on ? " on" : ""}`} onClick={() => click(it.id)} onMouseEnter={() => onHover?.(it.id)} onMouseLeave={() => onHover?.(null)} style={{ ["--c" as string]: c }}>
                    <rect x={b.x0 - pad} y={b.y0 - pad} width={b.x1 - b.x0 + 2 * pad} height={b.y1 - b.y0 + 2 * pad} rx={4 * u} fill={c} fillOpacity={on ? 0.2 : 0.1} stroke={c} strokeWidth={on ? 3.2 : 2.2} vectorEffect="non-scaling-stroke" />
                    {on && <rect x={b.x0 - pad * 2.4} y={b.y0 - pad * 2.4} width={b.x1 - b.x0 + 4.8 * pad} height={b.y1 - b.y0 + 4.8 * pad} rx={7 * u} fill="none" stroke={c} strokeWidth={1} strokeOpacity={0.55} vectorEffect="non-scaling-stroke" className="pulse-ring" />}
                    {it.marker != null && (
                      <g transform={`translate(${b.x1 + pad}, ${b.y0 - pad})`}>
                        <circle r={12 * u} fill={c} stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                        <text textAnchor="middle" dy={4.3 * u} fontSize={12 * u} className="svg-marker">
                          {it.marker}
                        </text>
                      </g>
                    )}
                    {on && it.caption && <Chip x={b.x0 - pad} y={b.y1 + pad + 6 * u} u={u} color={c} text={it.caption} />}
                  </g>
                );
              })}
          </svg>
        </div>
      )}
      {scanning && (
        <div className="scan">
          <div className="scan-beam" />
          <div className="scan-grid" />
        </div>
      )}
      {(show.anchors || show.drawing) && (
        <div className="viewer-legend">
          {show.drawing && <span><i className="sq" style={{ ["--c" as string]: "#5be3ff" }} /> Drawing, laid onto the photo</span>}
          {layers.anchors && (
            <>
              <span><i style={{ ["--c" as string]: "#2bd49a" }} /> Anchor fits the drawing</span>
              <span><i style={{ ["--c" as string]: "#ff5468" }} /> Off-pattern: points to a misplaced part</span>
              <span><i className="ring" style={{ ["--c" as string]: "#5be3ff" }} /> Where the drawing expects it</span>
            </>
          )}
        </div>
      )}
      {children}
      {interactive && (
        <div className="viewer-hud" onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
          <button className="btn btn-sm btn-icon btn-ghost" onClick={() => zoomAt(1 / 1.4, box.w / 2, box.h / 2, true)} aria-label="Zoom out">
            <Minus />
          </button>
          <span className="mono tiny faint" style={{ minWidth: 42, textAlign: "center" }}>
            {zoomPct}%
          </span>
          <button className="btn btn-sm btn-icon btn-ghost" onClick={() => zoomAt(1.4, box.w / 2, box.h / 2, true)} aria-label="Zoom in">
            <Plus />
          </button>
          <button className="btn btn-sm btn-icon btn-ghost" onClick={() => { setAnim(true); setView(fit); }} aria-label="Fit">
            <Maximize2 />
          </button>
        </div>
      )}
    </div>
  );
}
