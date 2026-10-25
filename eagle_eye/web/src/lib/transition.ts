/** #2 eye-blink page transition: two aurora lids with curved edges close from the top and bottom, the route name
 *  scrambles in on the closed lid, the new page mounts behind it, and the lids open. Under 0.9 s in total. In Calm it
 *  is an instant route change. */
import { calm, gsap } from "./gsap";

let busy = false;

const jump = (hash: string) => {
  window.location.hash = hash;
  window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
};

export function blinkTo(hash: string, label: string) {
  const h = hash.startsWith("#") ? hash : `#${hash}`;
  if (window.location.hash === h || (h === "#/" && !window.location.hash)) return;
  const top = document.querySelector(".lid-top");
  const bottom = document.querySelector(".lid-bottom");
  const lab = document.querySelector<HTMLElement>(".lid-label");
  if (calm() || !top || !bottom || !lab) return jump(h);
  if (busy) return;
  busy = true;
  lab.textContent = "";
  window.dispatchEvent(new Event("ee:blink"));
  gsap.timeline({ onComplete: () => void (busy = false) })
    .set([top, bottom], { visibility: "visible" })
    .fromTo(top, { y: 0, yPercent: -101 }, { yPercent: 0, duration: 0.26, ease: "power3.in" })
    .fromTo(bottom, { y: 0, yPercent: 101 }, { yPercent: 0, duration: 0.26, ease: "power3.in" }, "<")
    .set(lab, { autoAlpha: 1 }, "-=0.04")
    .to(lab, { duration: 0.24, scrambleText: { text: label.toUpperCase(), chars: "CBPSX0123456789:", speed: 1 } }, "<")
    .add(() => jump(h))
    .to(lab, { autoAlpha: 0, duration: 0.12 }, "+=0.06")
    .to(top, { yPercent: -101, duration: 0.3, ease: "power3.out" }, "<")
    .to(bottom, { yPercent: 101, duration: 0.3, ease: "power3.out" }, "<")
    .set([top, bottom], { visibility: "hidden" });
}
