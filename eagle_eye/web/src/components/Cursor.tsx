/** #21 crosshair reticle (Overview): follows the pointer, snaps to registration anchors inside an anchor zone, and
 *  grows with a scrambled label over [data-cursor] targets. Mouse / trackpad only; off in Calm. */
import { useEffect, useRef } from "react";
import { calm, fine, gsap } from "../lib/gsap";

export function Cursor() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current!;
    if (calm() || !fine()) {
      el.style.display = "none";
      return;
    }
    gsap.set(el, { xPercent: -50, yPercent: -50, autoAlpha: 0 });
    const cx = gsap.quickTo(el, "x", { duration: 0.25, ease: "power3" });
    const cy = gsap.quickTo(el, "y", { duration: 0.25, ease: "power3" });
    const label = el.querySelector<HTMLElement>(".cursor-label")!;
    let shown = false;
    let over: HTMLElement | null = null;

    const nearestAnchor = (zone: Element, x: number, y: number, r: number) => {
      let best: { x: number; y: number } | null = null;
      let bd = r;
      zone.querySelectorAll("[data-anchor]").forEach((a) => {
        const b = a.getBoundingClientRect();
        const ax = b.left + b.width / 2;
        const ay = b.top + b.height / 2;
        const d = Math.hypot(ax - x, ay - y);
        if (d < bd) { bd = d; best = { x: ax, y: ay }; }
      });
      return best as { x: number; y: number } | null;
    };

    const move = (e: PointerEvent) => {
      if (!shown) { gsap.to(el, { autoAlpha: 1, duration: 0.2 }); shown = true; }
      const t = e.target as Element;
      const zone = t instanceof Element ? t.closest("[data-anchor-zone]") : null;
      const a = zone ? nearestAnchor(zone, e.clientX, e.clientY, 40) : null;
      el.classList.toggle("snap", !!a);
      cx(a ? a.x : e.clientX);
      cy(a ? a.y : e.clientY);
    };
    const enter = (e: PointerEvent) => {
      const t = (e.target as Element).closest?.<HTMLElement>("[data-cursor]");
      if (!t || t === over) return;
      over = t;
      el.classList.add("on");
      gsap.to(el.querySelector(".cursor-ring"), { scale: 1.8, duration: 0.3, overwrite: true });
      gsap.to(label, { duration: 0.4, scrambleText: { text: t.dataset.cursor!, chars: "upperCase", speed: 0.6 }, overwrite: true });
    };
    const leave = (e: PointerEvent) => {
      if (!over || over.contains(e.relatedTarget as Node | null)) return;
      over = null;
      el.classList.remove("on");
      gsap.to(el.querySelector(".cursor-ring"), { scale: 1, duration: 0.3, overwrite: true });
      label.textContent = "";
    };
    const hide = () => { gsap.to(el, { autoAlpha: 0, duration: 0.2 }); shown = false; };
    window.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerover", enter, { passive: true });
    document.addEventListener("pointerout", leave, { passive: true });
    document.documentElement.addEventListener("pointerleave", hide);
    return () => {
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerover", enter);
      document.removeEventListener("pointerout", leave);
      document.documentElement.removeEventListener("pointerleave", hide);
    };
  }, []);

  return (
    <div className="cursor" ref={ref} aria-hidden="true">
      <span className="cursor-ring">
        <i /><i /><i /><i />
      </span>
      <span className="cursor-label mono" />
    </div>
  );
}
