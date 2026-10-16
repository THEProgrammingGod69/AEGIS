import { MoveHorizontal } from "lucide-react";
import { useRef, useState } from "react";

/** Before/after wipe between two images of the same cabinet. */
export function CompareSlider({ before, after, labelBefore, labelAfter, aspect }: {
  before: string; after: string; labelBefore: string; labelAfter: string; aspect: number;
}) {
  const [p, setP] = useState(50);
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const move = (x: number) => {
    const r = ref.current!.getBoundingClientRect();
    setP(Math.max(0, Math.min(100, ((x - r.left) / r.width) * 100)));
  };
  return (
    <div
      ref={ref}
      className="compare"
      style={{ aspectRatio: String(aspect) }}
      onPointerDown={(e) => { dragging.current = true; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); move(e.clientX); }}
      onPointerMove={(e) => dragging.current && move(e.clientX)}
      onPointerUp={() => (dragging.current = false)}
    >
      <img src={after} alt={labelAfter} draggable={false} />
      <img src={before} alt={labelBefore} draggable={false} style={{ clipPath: `inset(0 ${100 - p}% 0 0)` }} />
      <span className="compare-label left">{labelBefore}</span>
      <span className="compare-label right">{labelAfter}</span>
      <div className="compare-handle" style={{ left: `${p}%` }}>
        <span><MoveHorizontal size={16} /></span>
      </div>
    </div>
  );
}
