import { Draggable } from "gsap/Draggable";
import { InertiaPlugin } from "gsap/InertiaPlugin";
import { MoveHorizontal } from "lucide-react";
import { useRef } from "react";
import { calm, gsap, useGSAP } from "../lib/gsap";

gsap.registerPlugin(Draggable, InertiaPlugin);

/** Before/after wipe between two images of the same cabinet (#33): the handle is a Draggable with inertia, so a flick
 *  glides on; click anywhere to jump there; arrow keys nudge it. */
export function CompareSlider({ before, after, labelBefore, labelAfter, aspect }: {
  before: string; after: string; labelBefore: string; labelAfter: string; aspect: number;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useGSAP(() => {
    const box = ref.current!;
    const handle = box.querySelector<HTMLElement>(".compare-handle")!;
    const top = box.querySelector<HTMLElement>(".compare-before")!;
    const sync = (x: number) => {
      const w = box.clientWidth || 1;
      top.style.clipPath = `inset(0 ${Math.max(0, 100 - (x / w) * 100)}% 0 0)`;
      handle.setAttribute("aria-valuenow", String(Math.round((x / w) * 100)));
    };
    gsap.set(handle, { x: box.clientWidth / 2 });
    sync(box.clientWidth / 2);
    const [d] = Draggable.create(handle, {
      type: "x", bounds: box, inertia: !calm(),
      onDrag() { sync(this.x); },
      onThrowUpdate() { sync(this.x); },
    });
    const jump = (e: PointerEvent) => {
      if ((e.target as Element).closest(".compare-handle")) return;
      const r = box.getBoundingClientRect();
      const x = Math.max(0, Math.min(r.width, e.clientX - r.left));
      gsap.to(handle, { x, duration: calm() ? 0 : 0.45, ease: "expo.out", onUpdate: () => sync(Number(gsap.getProperty(handle, "x"))), onComplete: () => void d.update() });
    };
    const key = (e: KeyboardEvent) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const w = box.clientWidth;
      const x = Math.max(0, Math.min(w, Number(gsap.getProperty(handle, "x")) + (e.key === "ArrowLeft" ? -0.05 : 0.05) * w));
      gsap.set(handle, { x });
      sync(x);
      d.update();
    };
    const ro = new ResizeObserver(() => {
      d.applyBounds(box);
      d.update();
      sync(d.x);
    });
    ro.observe(box);
    box.addEventListener("pointerdown", jump);
    handle.addEventListener("keydown", key);
    return () => {
      ro.disconnect();
      box.removeEventListener("pointerdown", jump);
      handle.removeEventListener("keydown", key);
    };
  }, { scope: ref });

  return (
    <div ref={ref} className="compare" style={{ aspectRatio: String(aspect) }}>
      <img src={after} alt={labelAfter} draggable={false} />
      <img className="compare-before" src={before} alt={labelBefore} draggable={false} />
      <span className="compare-label left">{labelBefore}</span>
      <span className="compare-label right">{labelAfter}</span>
      <div className="compare-handle" role="slider" tabIndex={0} aria-label="Before and after" aria-valuemin={0} aria-valuemax={100} aria-valuenow={50}>
        <span><MoveHorizontal size={16} /></span>
      </div>
    </div>
  );
}
