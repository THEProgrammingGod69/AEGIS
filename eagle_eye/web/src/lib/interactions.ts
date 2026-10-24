/** Pointer feedback for the whole console, from four delegated listeners instead of one per element, so cards and
 *  buttons rendered later (async data, route changes) get it for free:
 *  #22 magnetic buttons ([data-magnetic]), #23 spotlight ([data-spotlight]), #24 3D tilt ([data-tilt]),
 *  #26 icon line-draw on hover (buttons, [data-draw]). Mouse / trackpad only, never in Calm. */
import { calm, fine, gsap } from "./gsap";

type Quick = ReturnType<typeof gsap.quickTo>;
const tilts = new WeakMap<Element, { rx: Quick; ry: Quick }>();
const mags = new WeakMap<Element, { x: Quick; y: Quick }>();

const DRAW = ".btn, [data-draw], .new-card, .idea, .nav-item";

function tiltOf(el: HTMLElement) {
  let t = tilts.get(el);
  if (!t) {
    gsap.set(el, { transformPerspective: 900 });
    t = { rx: gsap.quickTo(el, "rotationX", { duration: 0.5, ease: "power3" }), ry: gsap.quickTo(el, "rotationY", { duration: 0.5, ease: "power3" }) };
    tilts.set(el, t);
  }
  return t;
}

function magOf(el: HTMLElement) {
  let m = mags.get(el);
  if (!m) {
    m = { x: gsap.quickTo(el, "x", { duration: 0.4, ease: "power3" }), y: gsap.quickTo(el, "y", { duration: 0.4, ease: "power3" }) };
    mags.set(el, m);
  }
  return m;
}

/** Entered `el` from outside (pointerover bubbles, so filter moves between its own children). */
const entered = (e: PointerEvent, el: Element) => !el.contains(e.relatedTarget as Node | null);

let installed = false;

export function installInteractions() {
  if (installed || calm() || !fine()) return;
  installed = true;

  document.addEventListener(
    "pointermove",
    (e) => {
      const t = e.target as Element | null;
      if (!t || !(t instanceof Element)) return;
      const spot = t.closest<HTMLElement>("[data-spotlight]");
      if (spot) {
        const r = spot.getBoundingClientRect();
        spot.style.setProperty("--x", `${e.clientX - r.left}px`);
        spot.style.setProperty("--y", `${e.clientY - r.top}px`);
      }
      const tilt = t.closest<HTMLElement>("[data-tilt]");
      if (tilt) {
        const r = tilt.getBoundingClientRect();
        const k = Number(tilt.dataset.tilt || 8);
        const q = tiltOf(tilt);
        q.ry(((e.clientX - r.left) / r.width - 0.5) * k);
        q.rx(-((e.clientY - r.top) / r.height - 0.5) * k);
      }
      const mag = t.closest<HTMLElement>("[data-magnetic]");
      if (mag) {
        const r = mag.getBoundingClientRect();
        const q = magOf(mag);
        q.x((e.clientX - r.left - r.width / 2) * 0.25);
        q.y((e.clientY - r.top - r.height / 2) * 0.25);
      }
    },
    { passive: true },
  );

  document.addEventListener(
    "pointerout",
    (e) => {
      const t = e.target as Element | null;
      if (!t || !(t instanceof Element)) return;
      const tilt = t.closest<HTMLElement>("[data-tilt]");
      if (tilt && entered(e, tilt)) {
        const q = tiltOf(tilt);
        q.rx(0);
        q.ry(0);
      }
      const mag = t.closest<HTMLElement>("[data-magnetic]");
      if (mag && entered(e, mag)) {
        const q = magOf(mag);
        q.x(0);
        q.y(0);
      }
    },
    { passive: true },
  );

  document.addEventListener(
    "pointerover",
    (e) => {
      const t = e.target as Element | null;
      if (!t || !(t instanceof Element)) return;
      const host = t.closest<HTMLElement>(DRAW);
      if (!host || !entered(e, host) || (host as HTMLButtonElement).disabled) return;
      const strokes = host.querySelectorAll<SVGElement>("svg.lucide path, svg.lucide circle, svg.lucide line, svg.lucide rect, svg.lucide polyline");
      if (!strokes.length || strokes.length > 14) return;
      gsap.fromTo(strokes, { drawSVG: "0%" }, { drawSVG: "100%", duration: 0.5, stagger: 0.04, ease: "power2.out", overwrite: true, clearProps: "strokeDasharray,strokeDashoffset" });
    },
    { passive: true },
  );
}

/* ---------- Bonus: the X-ray Easter egg. Press X anywhere outside inputs: every photo shows its GA overlay and the
   logo's eye "scans". Components subscribe with onXray(). ---------- */
const xrayListeners = new Set<(on: boolean) => void>();
export const xrayOn = () => document.documentElement.classList.contains("xray");
export function onXray(fn: (on: boolean) => void) {
  xrayListeners.add(fn);
  return () => void xrayListeners.delete(fn);
}
export function toggleXray(force?: boolean) {
  const on = document.documentElement.classList.toggle("xray", force);
  xrayListeners.forEach((f) => f(on));
  if (!calm()) gsap.fromTo(".logo .iris", { scale: 1, transformOrigin: "50% 50%" }, { scale: 1.4, yoyo: true, repeat: 1, duration: 0.2 });
  return on;
}

export function installXray() {
  window.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "x" || e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target as HTMLElement;
    if (t.closest("input, textarea, select, [contenteditable]")) return;
    toggleXray();
  });
}

/* ---------- Click spark (React Bits-style): aurora sparks burst from primary buttons. One shared canvas that only
   draws while sparks are alive. ---------- */
interface Spark { x: number; y: number; a: number; t: number; c: string }
const SPARK_C = ["#004b8d", "#0a66e8", "#6c47d9", "#00b8e0", "#7fe7ff"];

export function installClickSpark() {
  if (calm()) return;
  const cv = document.createElement("canvas");
  cv.className = "spark-canvas";
  cv.setAttribute("aria-hidden", "true");
  document.body.appendChild(cv);
  const ctx = cv.getContext("2d")!;
  let sparks: Spark[] = [];
  let raf = 0;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const size = () => {
    cv.width = innerWidth * dpr;
    cv.height = innerHeight * dpr;
  };
  size();
  window.addEventListener("resize", size, { passive: true });
  const draw = (now: number) => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    sparks = sparks.filter((s) => now - s.t < 420);
    for (const s of sparks) {
      const k = (now - s.t) / 420;
      const e = 1 - Math.pow(1 - k, 3);
      const d = 8 + 26 * e;
      const len = 9 * (1 - k);
      ctx.strokeStyle = s.c;
      ctx.globalAlpha = 1 - k;
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(s.x + Math.cos(s.a) * d, s.y + Math.sin(s.a) * d);
      ctx.lineTo(s.x + Math.cos(s.a) * (d + len), s.y + Math.sin(s.a) * (d + len));
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    raf = sparks.length ? requestAnimationFrame(draw) : 0;
  };
  document.addEventListener(
    "click",
    (e) => {
      const host = (e.target as Element | null)?.closest?.(".btn-primary, .btn-brand, [data-spark]");
      if (!host || e.detail === 0) return;
      const now = performance.now();
      for (let i = 0; i < 10; i++) sparks.push({ x: e.clientX, y: e.clientY, a: (i / 10) * Math.PI * 2 + Math.random() * 0.3, t: now, c: SPARK_C[i % SPARK_C.length] });
      if (!raf) raf = requestAnimationFrame(draw);
    },
    { passive: true },
  );
}
