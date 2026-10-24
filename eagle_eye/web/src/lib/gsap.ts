/** GSAP set-up (UI & Motion Guide v2, section 10). Every plugin is free for commercial use; the always-on ones are
 *  registered here, the page-specific ones (Flip, Draggable, Physics2D, MotionPath, Observer...) in the lazily
 *  loaded pages that use them, so the first paint stays light. */
import { gsap } from "gsap";
import { useGSAP } from "@gsap/react";
import { CustomEase } from "gsap/CustomEase";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { ScrambleTextPlugin } from "gsap/ScrambleTextPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText, ScrambleTextPlugin, DrawSVGPlugin, CustomEase);
CustomEase.create("ee", "0.22, 1, 0.36, 1");
gsap.defaults({ ease: "ee", duration: 0.6 });

const read = (k: string) => {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
};

const CALM =
  typeof window !== "undefined" &&
  (window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    new URLSearchParams(window.location.search).has("calm") ||
    read("ee_motion") === "calm");

if (typeof document !== "undefined") document.documentElement.classList.toggle("calm", CALM);

/** Calm = reduced motion everywhere: every snippet returns early to its final frame (CSS default). */
export const calm = () => CALM;
/** Mouse / trackpad, not touch: cursor, magnetic, tilt and spotlight effects run only here. */
export const fine = () => typeof window !== "undefined" && window.matchMedia("(pointer: fine)").matches;

/** Motion: Full / Calm, from the Ctrl K palette. Stored per device; the page reloads into the new mode. */
export function setMotion(mode: "full" | "calm") {
  try {
    localStorage.setItem("ee_motion", mode);
  } catch {
    /* private window: the ?calm flag still works */
  }
  const u = new URL(window.location.href);
  if (mode === "full") u.searchParams.delete("calm");
  window.location.replace(u.toString());
}

/* The opening chain: the preloader's onDone starts the hero (registration sequence, headline), so the two WOWs run
   as one 5-second opening instead of competing. Resolved at once when no preloader plays. */
let release: () => void = () => {};
export const intro = new Promise<void>((r) => (release = r));
let introOver = false;
export function introDone() {
  if (introOver) return;
  introOver = true;
  release();
}
export const introPlayed = () => introOver;

export { gsap, useGSAP, ScrollTrigger, SplitText };
