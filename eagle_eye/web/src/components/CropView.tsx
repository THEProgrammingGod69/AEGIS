import { useSize } from "../lib/hooks";
import type { Pt } from "../lib/types";

/**
 * Shows a window of a large image, scaled to fit, with an outline drawn on top. Used by the hosted showcase to
 * build expected / found / aligned proof crops in the browser (the live engine renders them server-side).
 * `size` is the image's coordinate space (it may be served at a lower resolution).
 */
export function CropView({ src, size, rect, outline, color, bg }: {
  src: string; size: [number, number]; rect: [number, number, number, number]; outline: Pt[]; color: string; bg?: string;
}) {
  const [ref, box] = useSize<HTMLDivElement>();
  const [x0, y0, x1, y1] = rect;
  const rw = x1 - x0;
  const rh = y1 - y0;
  const s = box.w && box.h ? Math.min(box.w / rw, box.h / rh) : 0;
  return (
    <div ref={ref} style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", background: bg }}>
      {s > 0 && (
        <div style={{ position: "relative", width: rw * s, height: rh * s, overflow: "hidden" }}>
          <img src={src} alt="" draggable={false}
            style={{ position: "absolute", left: -x0 * s, top: -y0 * s, width: size[0] * s, height: size[1] * s, maxWidth: "none", maxHeight: "none" }} />
          <svg viewBox={`${x0} ${y0} ${rw} ${rh}`} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
            <polygon points={outline.map((p) => p.join(",")).join(" ")} fill="none" stroke={color} strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
          </svg>
        </div>
      )}
    </div>
  );
}
