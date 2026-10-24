/** Reusable motion pieces from the v2 catalogue. Each returns early to its final frame in Calm. */
import { useEffect, useRef, type CSSProperties, type ReactNode, type RefObject } from "react";
import { TextPlugin } from "gsap/TextPlugin";
import { ScrollTrigger, calm, gsap, useGSAP } from "../lib/gsap";

gsap.registerPlugin(TextPlugin);

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
      strips.forEach((el) => gsap.set(el, { y: 0, yPercent: at(el) }));
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

/** #38 charts draw when they scroll in (and again when their data changes): [data-draw-line] strokes draw,
 *  [data-grow-y] bars grow from the baseline, [data-grow-x] bars from the left, [data-pop] dots pop in. */
export function useChartIn(scope: RefObject<Element | null>, deps: unknown[] = []) {
  useGSAP(() => {
    const root = scope.current;
    if (!root) return;
    root.setAttribute("data-chart", "");
    if (calm()) return;
    // a nested chart animates its own marks: two from() tweens on one element would freeze it at its start value
    const own = (sel: string) => Array.from(root.querySelectorAll(sel)).filter((el) => el.parentElement?.closest("[data-chart]") === root);
    const tl = gsap.timeline({ scrollTrigger: { trigger: root, start: "top 88%", once: true } });
    const ys = own("[data-grow-y]");
    if (ys.length) tl.from(ys, { scaleY: 0, transformOrigin: "50% 100%", duration: 0.6, stagger: 0.04, ease: "expo.out" }, 0);
    const xs = own("[data-grow-x]");
    if (xs.length) tl.from(xs, { scaleX: 0, transformOrigin: "0% 50%", duration: 0.8, stagger: 0.05, ease: "expo.out" }, 0);
    const lines = own("[data-draw-line]");
    if (lines.length) tl.from(lines, { drawSVG: 0, duration: 1.2, stagger: 0.15, ease: "power2.inOut" }, 0.15);
    const dots = own("[data-pop]");
    if (dots.length) tl.from(dots, { scale: 0, opacity: 0, transformOrigin: "50% 50%", duration: 0.4, stagger: 0.025, ease: "back.out(2)" }, 0.45);
  }, { scope, dependencies: deps, revertOnUpdate: true });
}

/** #38 progress ring: the value arc draws from 0 to its share (e.g. first-pass yield 36 of 41). */
export function Ring({ value, size = 64, stroke = 7, color = "var(--azure)", children }: {
  value: number; size?: number; stroke?: number; color?: string; children?: ReactNode;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const r = (size - stroke) / 2;
  const v = Math.max(0, Math.min(1, value));
  useGSAP(() => {
    const arc = ref.current!.querySelector(".ring-value")!;
    if (calm()) return;
    gsap.fromTo(arc, { drawSVG: "0%" }, { drawSVG: `${v * 100}%`, duration: 1.2, ease: "power3.out", scrollTrigger: { trigger: ref.current, start: "top 92%", once: true } });
  }, { dependencies: [v] });
  return (
    <span className="ring" style={{ width: size, height: size }}>
      <svg ref={ref} viewBox={`0 0 ${size} ${size}`} width={size} height={size} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} className="ring-track" strokeWidth={stroke} />
        <circle className="ring-value" cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} stroke={color}
          strokeDasharray={`${2 * Math.PI * r * v} ${2 * Math.PI * r}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      {children && <span className="ring-label">{children}</span>}
    </span>
  );
}

/** #36 engine log typewriter inside a dark device panel: each new line types itself out (TextPlugin), the caret
 *  blinks on the last one. Lines added later (a live job streaming) type in as they arrive. */
export function EngineLog({ lines, title = "ENGINE LOG", className, startOnView = true }: {
  lines: { t: string; k: string; v: string; tone?: "pass" | "fail" | "review" | "accent" }[]; title?: string; className?: string; startOnView?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const typed = useRef(0);
  useGSAP(() => {
    const rows = gsap.utils.toArray<HTMLElement>(".log-line", ref.current);
    const fresh = rows.slice(typed.current);
    typed.current = rows.length;
    if (calm() || !fresh.length) return;
    const tl = gsap.timeline({ paused: startOnView && fresh.length === rows.length });
    fresh.forEach((row, i) => {
      const msg = row.querySelector<HTMLElement>(".msg")!;
      const text = msg.dataset.text ?? "";
      tl.set(row, { autoAlpha: 1 }, i * 0.22).fromTo(msg, { text: "" }, { text: { value: text }, duration: Math.min(0.9, text.length * 0.012), ease: "none" }, i * 0.22);
    });
    gsap.set(fresh, { autoAlpha: 0 });
    if (startOnView && fresh.length === rows.length) ScrollTrigger.create({ trigger: ref.current, start: "top 90%", once: true, onEnter: () => void tl.play() });
  }, { scope: ref, dependencies: [lines.length] });
  return (
    <div className={`log-panel${className ? ` ${className}` : ""}`} ref={ref}>
      <div className="log-head mono"><span className="rv-dots" aria-hidden="true"><i /><i /><i /></span>{title}</div>
      <div className="log-body mono">
        {lines.map((l, i) => (
          <div key={i} className="log-line">
            <span className="t">{l.t}</span>
            <span className="k">{l.k}</span>
            <span className={`msg${l.tone ? ` ${l.tone}` : ""}`} data-text={l.v}>{l.v}</span>
          </div>
        ))}
        <span className="caret" aria-hidden="true" />
      </div>
    </div>
  );
}
