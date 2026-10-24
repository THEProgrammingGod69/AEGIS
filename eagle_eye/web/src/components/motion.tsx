/** Reusable motion pieces from the v2 catalogue. Each returns early to its final frame in Calm. */
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { ScrollTrigger, calm, gsap, useGSAP } from "../lib/gsap";

/** #20 aurora scroll-progress bar: transform-origin left, scaleX follows the page (smoothed like scrub: 0.3). */
export function ScrollProgress() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current!;
    if (calm()) {
      el.style.display = "none";
      return;
    }
    const to = gsap.quickTo(el, "scaleX", { duration: 0.3, ease: "power3" });
    let raf = 0;
    const tick = () => {
      raf = 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      to(max > 8 ? Math.min(1, window.scrollY / max) : 0);
    };
    const on = () => void (raf ||= requestAnimationFrame(tick));
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on, { passive: true });
    window.addEventListener("hashchange", on);
    const ro = new ResizeObserver(on);
    ro.observe(document.body);
    tick();
    return () => {
      window.removeEventListener("scroll", on);
      window.removeEventListener("resize", on);
      window.removeEventListener("hashchange", on);
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);
  return <div ref={ref} className="scroll-progress" aria-hidden="true" />;
}

/** #17 odometer: every digit is a 0-9 strip tweened by yPercent, rolling in once when it scrolls into view. */
export function Odometer({ value, className, style, delay = 0 }: { value: number; className?: string; style?: CSSProperties; delay?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const digits = String(Math.max(0, Math.round(value))).split("");
  useGSAP(() => {
    const strips = gsap.utils.toArray<HTMLElement>(".odo-strip", ref.current);
    const at = (el: HTMLElement) => -10 * Number(el.dataset.d);
    if (calm()) {
      strips.forEach((el) => gsap.set(el, { yPercent: at(el) }));
      return;
    }
    strips.forEach((el, i) =>
      gsap.fromTo(el, { yPercent: 0 }, {
        yPercent: at(el), duration: 1.5 + (strips.length - i) * 0.18, delay, ease: "power3.out",
        scrollTrigger: { trigger: ref.current, start: "top 92%", once: true },
      }),
    );
  }, { scope: ref, dependencies: [value] });
  return (
    <span ref={ref} className={`odo${className ? ` ${className}` : ""}`} style={style} aria-label={String(value)} role="img">
      {digits.map((d, i) => (
        <span key={`${i}-${digits.length}`} className="odo-d" aria-hidden="true">
          <span className="odo-strip" data-d={d}>
            {"0123456789".split("").map((n) => <span key={n}>{n}</span>)}
          </span>
        </span>
      ))}
    </span>
  );
}

/** #16 reversible infinite marquee + #15 scroll-velocity skew: content duplicated once, speeds up and flips
 *  direction with the scroll, skews with scroll speed and settles back to 0. Paused off-screen. */
export function Marquee({ children, speed = 22, className }: { children: ReactNode; speed?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (calm()) return;
    const inner = ref.current!.querySelector<HTMLElement>(".marquee-inner")!;
    const loop = gsap.to(inner, { xPercent: -50, ease: "none", duration: speed, repeat: -1 });
    loop.totalTime(loop.duration() * 100); // head-room so reversing never hits time 0
    const skew = gsap.quickTo(ref.current, "skewX", { duration: 0.4, ease: "power3" });
    const clamp = gsap.utils.clamp(-6, 6);
    let settle: gsap.core.Tween | null = null;
    ScrollTrigger.create({
      trigger: ref.current, start: "top bottom", end: "bottom top",
      onToggle: (self) => (self.isActive ? loop.resume() : loop.pause()),
      onUpdate: (self) => {
        const v = self.getVelocity();
        gsap.to(loop, { timeScale: self.direction * Math.min(4, 1 + Math.abs(v) / 800), duration: 0.3, overwrite: true });
        skew(clamp(v / -400));
        settle?.kill();
        settle = gsap.delayedCall(0.15, () => skew(0));
      },
    });
  }, { scope: ref });
  return (
    <div ref={ref} className={`marquee${className ? ` ${className}` : ""}`}>
      <div className="marquee-inner">
        <div className="marquee-set">{children}</div>
        <div className="marquee-set" aria-hidden="true">{children}</div>
      </div>
    </div>
  );
}

/** #12 scramble a label into place (ScrambleText) when it scrolls into view. */
export function Scramble({ text, chars = "0123456789.", className, delay = 0, as: Tag = "span" }: {
  text: string; chars?: string; className?: string; delay?: number; as?: "span" | "b" | "div";
}) {
  const ref = useRef<HTMLElement>(null);
  useGSAP(() => {
    const el = ref.current!;
    el.textContent = text; // GSAP owns this text node, so React never patches a node the plugin replaced
    if (calm()) return;
    gsap.to(el, {
      duration: 0.9, delay, scrambleText: { text, chars, speed: 0.6, revealDelay: 0.25 },
      scrollTrigger: { trigger: el, start: "top 95%", once: true },
    });
  }, { dependencies: [text] });
  return <Tag ref={ref as never} className={className} aria-label={text} />;
}
