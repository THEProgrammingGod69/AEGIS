/** #6 confetti in brand colours (Physics2D): fired on a positive completion only, a signed-off work order or a
 *  perfect Fault Forge score. Never on a FAIL screen, never in Calm. */
import { Physics2DPlugin } from "gsap/Physics2DPlugin";
import { calm, gsap } from "./gsap";

gsap.registerPlugin(Physics2DPlugin);

const COLS = ["#004b8d", "#0a66e8", "#6c47d9", "#00b8e0", "#7fe7ff", "#08875a"];

export function confetti(x: number, y: number, n = 90) {
  if (calm()) return;
  for (let i = 0; i < n; i++) {
    const p = document.createElement("i");
    p.className = "confetti";
    p.style.background = COLS[i % COLS.length];
    if (i % 3 === 0) p.style.borderRadius = "50%";
    document.body.appendChild(p);
    gsap.set(p, { x, y, rotation: gsap.utils.random(0, 360) });
    gsap.to(p, {
      duration: gsap.utils.random(1.2, 2.2), ease: "none", opacity: 0,
      rotation: "+=" + gsap.utils.random(-540, 540),
      physics2D: { velocity: gsap.utils.random(300, 750), angle: gsap.utils.random(200, 340), gravity: 900 },
      onComplete: () => p.remove(),
    });
  }
}

/** Confetti from the centre of an element. */
export function confettiFrom(el: Element | null, n?: number) {
  if (!el) return;
  const r = el.getBoundingClientRect();
  confetti(r.left + r.width / 2, r.top + r.height / 2, n);
}
