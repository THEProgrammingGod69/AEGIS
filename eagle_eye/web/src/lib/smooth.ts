/** Smooth wheel scrolling for the Overview story only (Lenis, driven by GSAP's ticker so ScrollTrigger scrubs and
 *  pins stay in sync). Working pages keep native scrolling: the photo viewer's wheel-zoom must not fight it.
 *  Off for touch (native momentum is better there) and in Calm. */
import Lenis from "lenis";
import { useEffect } from "react";
import { ScrollTrigger, calm, fine, gsap } from "./gsap";

let lenis: Lenis | null = null;

export function useSmoothScroll() {
  useEffect(() => {
    if (calm() || !fine()) return;
    const l = new Lenis({ lerp: 0.11, wheelMultiplier: 1, smoothWheel: true });
    lenis = l;
    l.on("scroll", ScrollTrigger.update);
    const tick = (t: number) => l.raf(t * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    return () => {
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33);
      l.destroy();
      if (lenis === l) lenis = null;
    };
  }, []);
}

/** Scroll to an element through Lenis when it is running, natively otherwise. */
export function scrollToEl(el: Element | null, offset = 0) {
  if (!el) return;
  if (lenis) lenis.scrollTo(el as HTMLElement, { offset, duration: 1.4 });
  else el.scrollIntoView({ behavior: calm() ? "auto" : "smooth" });
}
