/** #1 eye-open preloader + iris wipe (first visit only, skipped in Calm). Storyboard A:
 *  0-0.5 s lids closed, a single Emerson-blue eye line, counter 0 → 40%
 *  0.5-1.0 s the lids ease apart (MorphSVG), the iris scales up from 0
 *  1.0-1.3 s crosshair ticks draw in (DrawSVG), the iris snaps with back.out, counter hits 100%
 *  1.3-1.9 s the iris grows into a circular window that reveals the page underneath.
 *  onDone starts the hero's registration sequence, so the two WOWs chain into one opening. */
import { MorphSVGPlugin } from "gsap/MorphSVGPlugin";
import { useRef } from "react";
import { createPortal } from "react-dom";
import { gsap, useGSAP } from "../lib/gsap";

gsap.registerPlugin(MorphSVGPlugin);

const CLOSED_TOP = "M16,60 C76,60 164,60 224,60";
const OPEN_TOP = "M16,60 C70,6 170,6 224,60";
const CLOSED_BOTTOM = "M16,60 C76,60 164,60 224,60";
const OPEN_BOTTOM = "M16,60 C70,114 170,114 224,60";
const CLOSED_EYE = "M16,60 C76,60 164,60 224,60 C164,60 76,60 16,60 Z";
const OPEN_EYE = "M16,60 C70,6 170,6 224,60 C170,114 70,114 16,60 Z";

export function Preloader({ onDone }: { onDone: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const pct = useRef<HTMLSpanElement>(null);
  const stage = useRef<HTMLSpanElement>(null);

  useGSAP(() => {
    const root = ref.current!;
    const html = document.documentElement;
    const prevOverflow = html.style.overflow;
    html.style.overflow = "hidden";
    const o = { v: 0 };
    const say = (s: string) => () => void (stage.current!.textContent = s);
    const far = Math.hypot(window.innerWidth, window.innerHeight);
    const iris = root.querySelector<SVGGElement>(".pl-iris")!;
    const irisPx = iris.getBoundingClientRect().width / 2 || 40;
    gsap.set(root, { "--r": "0px" });
    gsap.timeline({
      onComplete: () => {
        html.style.overflow = prevOverflow;
        onDone();
      },
    })
      .to(o, { v: 100, duration: 1.3, ease: "power2.inOut", onUpdate: () => void (pct.current!.textContent = `${String(Math.round(o.v)).padStart(3, "0")}%`) }, 0)
      .call(say("CALIBRATING"), [], 0.5)
      .to(".pl-lid-top", { morphSVG: OPEN_TOP, duration: 0.5, ease: "power3.out" }, 0.45)
      .to(".pl-lid-bottom", { morphSVG: OPEN_BOTTOM, duration: 0.5, ease: "power3.out" }, 0.45)
      .to(".pl-eye-shape", { morphSVG: OPEN_EYE, duration: 0.5, ease: "power3.out" }, 0.45)
      .from(iris, { scale: 0, transformOrigin: "50% 50%", duration: 0.5, ease: "back.out(2)" }, 0.6)
      .from(".pl-tick", { drawSVG: 0, duration: 0.3, stagger: 0.05 }, 1.0)
      .call(say("ANCHORED"), [], 1.05)
      .to(".pl-copy", { autoAlpha: 0, y: 8, duration: 0.25 }, 1.3)
      .set(root, { "--r": `${irisPx}px` }, 1.35)
      .to(root, { "--r": `${far}px`, duration: 0.7, ease: "expo.inOut" }, 1.35)
      .to(".pl-eye", { scale: 1.6, autoAlpha: 0, duration: 0.5, ease: "power2.in" }, 1.35);
  }, { scope: ref });

  return createPortal(
    <div ref={ref} className="preloader" role="status" aria-label="Loading EAGLE EYE">
      <svg className="pl-eye" viewBox="0 -30 240 180" fill="none" aria-hidden="true">
        <defs>
          <clipPath id="pl-clip">
            <path className="pl-eye-shape" d={CLOSED_EYE} />
          </clipPath>
          <linearGradient id="pl-aurora" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#004b8d" />
            <stop offset="0.4" stopColor="#0a66e8" />
            <stop offset="0.7" stopColor="#6c47d9" />
            <stop offset="1" stopColor="#00b8e0" />
          </linearGradient>
        </defs>
        <g clipPath="url(#pl-clip)">
          <path d={OPEN_EYE} fill="#fff" />
          <g className="pl-iris">
            <circle cx="120" cy="60" r="27" fill="#004b8d" />
            <circle cx="120" cy="60" r="21" fill="url(#pl-aurora)" />
            <circle cx="120" cy="60" r="14" fill="#00b8e0" />
            <circle cx="120" cy="60" r="9" fill="#fff" />
            <circle cx="120" cy="60" r="5.5" fill="#004b8d" />
          </g>
        </g>
        <path className="pl-lid-top" d={CLOSED_TOP} stroke="#004b8d" strokeWidth="3.2" strokeLinecap="round" />
        <path className="pl-lid-bottom" d={CLOSED_BOTTOM} stroke="#004b8d" strokeWidth="3.2" strokeLinecap="round" />
        <g stroke="#00b8e0" strokeWidth="2" strokeLinecap="round">
          <path className="pl-tick" d="M120 -6 V-28" />
          <path className="pl-tick" d="M120 126 V148" />
          <path className="pl-tick" d="M52 60 H76" />
          <path className="pl-tick" d="M164 60 H188" />
        </g>
      </svg>
      <div className="pl-copy mono">
        <span ref={stage}>LOADING ENGINE</span> · <span ref={pct}>000%</span>
      </div>
    </div>,
    document.body,
  );
}
