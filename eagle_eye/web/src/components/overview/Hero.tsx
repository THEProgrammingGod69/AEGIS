/** Overview hero (Figure 1 of the v2 guide): aurora mesh drifting behind (#39), a kinetic 3D-char headline with one
 *  aurora word (#7, #8), the dark device tilted in 3D and following the mouse (#10) while it runs the registration
 *  sequence on a real recorded inspection (#3), floating glass proof cards (#9) and a magnetic CTA with a shine
 *  pass (#22, #27). The preloader's onDone starts the sequence, so the opening reads as one chain. */
import { ArrowRight, Check, FlaskConical, Mic, Play, RotateCcw } from "lucide-react";
import { useRef } from "react";
import { ScrollTrigger, SplitText, calm, fine, gsap, intro, useGSAP } from "../../lib/gsap";
import { url } from "../../lib/api";
import { go } from "../../lib/router";
import { scrollToEl } from "../../lib/smooth";
import { ISSUE_TEXT, SHOW, SH, SW, bb, isFailedTag, pts } from "../../lib/showcase";
import type { SelfTest } from "../../lib/types";

const LAYOUT = [...SHOW.layout].sort((a, b) => bb(a.quad).x0 - bb(b.quad).x0);
const PASS_COUNT = SHOW.counts.PASS;
const FAIL_COUNT = SHOW.counts.FAIL;

/** #3 registration sequence inside the dark device: GA boxes draw, anchors lock and the drawing un-skews onto the
 *  photo, a beam sweeps and items flip to PASS, then the FAILs glitch in and the counters roll. */
function RegistrationViewport() {
  const root = useRef<HTMLDivElement>(null);
  const tlRef = useRef<gsap.core.Timeline | null>(null);

  useGSAP(() => {
    if (calm()) return;
    const hud = root.current!.querySelector<HTMLElement>(".rv-hud-text")!;
    const say = (t: string) => () => void gsap.to(hud, { duration: 0.45, scrambleText: { text: t, chars: "upperCase", speed: 0.8 }, overwrite: true });
    const tl = gsap.timeline({ paused: true, repeat: -1, repeatDelay: 7, delay: 0.2 });
    tl.call(say("Reading the GA drawing · 20 expected items"))
      .from(".rv-bp", { drawSVG: 0, duration: 0.7, ease: "power2.inOut" })
      .from(".ga-box", { drawSVG: 0, duration: 0.9, stagger: 0.035, ease: "power2.inOut" }, "-=0.35")
      .from(".ga-tag", { opacity: 0, duration: 0.3, stagger: 0.02 }, "-=0.6")
      .call(say(`${SHOW.anchors.length} label & ferrule anchors locked`))
      .from(".rv-anchor", { scale: 0, opacity: 0, transformOrigin: "50% 50%", stagger: 0.05, duration: 0.45, ease: "back.out(2.2)" }, "-=0.1")
      .fromTo(".ga-layer", { x: 150, y: -110, rotation: -2.5, skewX: 3, opacity: 0.55, svgOrigin: `${SW / 2} ${SH / 2}` },
        { x: 0, y: 0, rotation: 0, skewX: 0, opacity: 1, duration: 1, ease: "expo.out" }, "<")
      .call(say("Checking 41 items, one at a time"))
      .fromTo(".rv-beam", { xPercent: -100, autoAlpha: 1 }, { xPercent: 420, duration: 1.3, ease: "none" })
      .fromTo(".ga-box[data-pass]", { stroke: "#7fe7ff" }, { stroke: "#2bd49a", duration: 0.15, stagger: 0.05 }, "<0.1")
      .to(".rv-beam", { autoAlpha: 0, duration: 0.2 })
      .call(say(`${FAIL_COUNT} FAIL with proof · 0 false alarms`))
      .from(".fail-box", { opacity: 0, scale: 1.14, transformOrigin: "50% 50%", duration: 0.24, ease: "steps(3)", stagger: 0.14 })
      .from(".rv-count-fail", { textContent: 0, snap: { textContent: 1 }, duration: 0.6 }, "<")
      .from(".rv-count-pass", { textContent: 0, snap: { textContent: 1 }, duration: 0.8 }, "<");
    tlRef.current = tl;
    let started = false;
    let visible = true;
    const st = ScrollTrigger.create({
      trigger: root.current, start: "top bottom", end: "bottom top",
      onToggle: (self) => {
        visible = self.isActive;
        if (started) (visible ? tl.resume() : tl.pause());
      },
    });
    void intro.then(() => {
      started = true;
      if (visible || st.isActive) tl.play();
    });
  }, { scope: root });

  return (
    <div className="device rv" ref={root} data-anchor-zone="">
      <div className="rv-head">
        <span className="rv-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="mono rv-title">REGISTRATION VIEWPORT · CAB EE-DEMO-01</span>
        <button className="rv-replay" aria-label="Run the registration again" data-cursor="Replay"
          onClick={() => tlRef.current?.restart(true)}>
          <RotateCcw size={13} />
        </button>
      </div>
      <div className="rv-frame" style={{ aspectRatio: `${SW} / ${SH}` }}>
        <img src={url.sample("01", 1100)} alt="Emerson's example cabinet, inspected against its GA drawing" draggable={false} />
        <svg viewBox={`0 0 ${SW} ${SH}`} aria-hidden="true">
          <polygon className="rv-bp" points={pts(SHOW.backplate)} />
          <g className="ga-layer">
            {LAYOUT.map((l) => {
              const b = bb(l.quad);
              return (
                <g key={l.tag}>
                  <polygon className="ga-box" points={pts(l.quad)} data-pass={isFailedTag(l.tag) ? undefined : ""} />
                  {l.kind !== "terminal" && <text className="ga-tag" x={b.x0 + 14} y={b.y1 - 16}>{l.tag}</text>}
                </g>
              );
            })}
          </g>
          {SHOW.anchors.map((a, i) => (
            <circle key={a.tag + i} className={`rv-anchor${a.inlier ? "" : " out"}`} cx={a.p[0]} cy={a.p[1]} r={15} data-anchor="" />
          ))}
          {SHOW.issues.map((it) => {
            const b = bb(it.quad);
            return (
              <g key={it.id} className="fail-box">
                <rect x={b.x0 - 16} y={b.y0 - 16} width={b.x1 - b.x0 + 32} height={b.y1 - b.y0 + 32} rx={14} />
                <circle cx={b.x1 + 16} cy={b.y0 - 16} r={48} />
                <text x={b.x1 + 16} y={b.y0 + 4} textAnchor="middle">{it.marker}</text>
              </g>
            );
          })}
        </svg>
        <div className="rv-beam" aria-hidden="true" />
      </div>
      <div className="rv-foot mono">
        <span className="rv-hud"><span className="dot pulse" style={{ ["--c" as string]: "var(--accent)" }} /><span className="rv-hud-text">{FAIL_COUNT} FAIL with proof · 0 false alarms</span></span>
        <span className="rv-counts">
          <b style={{ color: "var(--pass)" }}><span className="rv-count-pass">{PASS_COUNT}</span> PASS</b>
          <b style={{ color: "var(--fail)" }}><span className="rv-count-fail">{FAIL_COUNT}</span> FAIL</b>
        </span>
      </div>
    </div>
  );
}

export function Hero({ s, onPresent }: { s?: SelfTest["summary"]; onPresent?: () => void }) {
  const root = useRef<HTMLElement>(null);
  const caught = s?.caught ?? 87;
  const planted = s?.planted ?? 87;
  const fa = s?.false_alarms ?? 0;
  const correct = s?.correct_items ?? 1950;
  const sec = (s?.sec_per_cabinet ?? 0.9).toFixed(1);

  useGSAP(() => {
    const el = root.current!;
    // #39 aurora mesh drift: new random targets every cycle, paused when the hero is off-screen
    const blobs = gsap.utils.toArray<HTMLElement>(".blob", el);
    const stage = el.querySelector<HTMLElement>(".hero-stage")!;
    const device = el.querySelector<HTMLElement>(".device-3d")!;
    if (calm()) return;
    const drift = blobs.map((b) => gsap.to(b, { x: "random(-120, 120)", y: "random(-80, 80)", scale: "random(0.85, 1.2)", duration: "random(8, 14)", repeat: -1, repeatRefresh: true, ease: "sine.inOut" }));
    // #8 aurora sweep on the key word (the one paint-based exception, kept to one word)
    const sweep = gsap.fromTo(".hero-title .aurora-text", { backgroundPosition: "0% 50%" }, { backgroundPosition: "100% 50%", duration: 6, ease: "sine.inOut", repeat: -1, yoyo: true });
    // #27 an idle shine pass every 6 s on the main CTA only
    const shine = gsap.fromTo(".hero-cta .btn-primary .shine", { xPercent: -120 }, { xPercent: 360, duration: 0.8, ease: "power2.inOut", repeat: -1, repeatDelay: 6, delay: 2.4 });
    // #9 floating proof cards: entrance on the outer element, idle float on an inner one (no conflicts)
    const floats = gsap.utils.toArray<HTMLElement>(".float-inner", el);
    const idle = gsap.to(floats, { y: "+=10", duration: 2.6, ease: "sine.inOut", yoyo: true, repeat: -1, stagger: { each: 0.5, from: "random" } });
    ScrollTrigger.create({
      trigger: el, start: "top bottom", end: "bottom top",
      onToggle: (self) => [...drift, sweep, shine, idle].forEach((t) => (self.isActive ? t.resume() : t.pause())),
    });

    // #7 kinetic headline: chars flip up in 3D (the aurora word moves as one, so its gradient stays whole)
    const title = el.querySelector<HTMLElement>(".hero-title")!;
    const word = title.querySelector(".aurora-text");
    const copy = el.querySelectorAll(".hero-copy > :not(h1)");
    const cards = el.querySelectorAll(".float");
    let ready = false;
    let lead: gsap.core.Timeline | null = null;
    SplitText.create(title, {
      type: "words, chars", wordsClass: "word", ignore: ".aurora-text", autoSplit: true,
      // a new timeline per split: SplitText kills the old one and keeps its progress when fonts load or it re-wraps
      onSplit: (self) => {
        lead = gsap.timeline({ paused: !ready })
          .from(self.chars, { yPercent: 120, rotationX: -90, opacity: 0, transformOrigin: "50% 100%", stagger: 0.018, duration: 0.8, ease: "expo.out" }, 0)
          .from(word, { yPercent: 60, rotationX: -70, opacity: 0, transformOrigin: "50% 100%", duration: 0.9, ease: "expo.out" }, 0.25)
          .from(copy, { y: 18, autoAlpha: 0, stagger: 0.08, duration: 0.8, ease: "expo.out" }, 0.2)
          .from(cards, { y: 40, opacity: 0, scale: 0.9, stagger: 0.12, duration: 0.7, ease: "back.out(1.6)" }, 0.9)
          .from(device, { y: 40, autoAlpha: 0, duration: 1, ease: "expo.out" }, 0.1);
        return lead;
      },
    });
    void intro.then(() => {
      ready = true;
      lead?.play();
    });

    // #10 the device tilts after the mouse (fine pointers only)
    gsap.set(device, { transformPerspective: 1400, rotationY: -9, rotationX: 4 });
    if (fine()) {
      const rx = gsap.quickTo(device, "rotationX", { duration: 0.6, ease: "power3" });
      const ry = gsap.quickTo(device, "rotationY", { duration: 0.6, ease: "power3" });
      const move = (e: PointerEvent) => {
        const r = stage.getBoundingClientRect();
        ry(-9 + ((e.clientX - r.left) / r.width - 0.5) * 12);
        rx(4 - ((e.clientY - r.top) / r.height - 0.5) * 8);
      };
      const leave = () => { rx(4); ry(-9); };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerleave", leave);
      return () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerleave", leave);
      };
    }
  }, { scope: root });

  return (
    <section className="hero-v2" ref={root}>
      <div className="hero-mesh" aria-hidden="true">
        <i className="blob b1" /><i className="blob b2" /><i className="blob b3" /><i className="blob b4" />
      </div>
      <div className="hero-inner">
        <div className="hero-copy">
          <span className="eyebrow"><b>TRACK 1</b> Built for Emerson · Code_Apex 3.0</span>
          <h1 className="hero-title">
            Every finding, <span className="aurora-text">anchored</span> to the drawing.
          </h1>
          <p className="hero-sub">
            EAGLE EYE reads the GA drawing and wire list, registers the cabinet photo to them, and checks every expected
            item at its known position. Proof for every FAIL. REVIEW when unsure. Never a silent PASS.
          </p>
          <div className="hero-cta">
            <button className="btn btn-primary btn-xl" data-magnetic="" data-cursor="Inspect" onClick={() => go("inspect/demo")}>
              <i className="shine" aria-hidden="true" />
              <Play /> <span>Run the live demo</span> <ArrowRight />
            </button>
            <button className="btn btn-xl" data-magnetic="" data-cursor="Scroll" onClick={() => scrollToEl(document.getElementById("story"))}>
              <span className="play-dot"><Play size={12} /></span> Watch it work
            </button>
          </div>
          <div className="hero-links">
            <button className="btn btn-ghost btn-sm" onClick={() => go("forge")}><FlaskConical /> Challenge it in Fault Forge</button>
            {onPresent && <button className="btn btn-ghost btn-sm" onClick={onPresent}><Mic /> Presenter mode</button>}
          </div>
          <div className="hero-trust mono">
            <span><Check size={12} /> Deterministic</span>
            <span><Check size={12} /> No training per cabinet</span>
            <span><Check size={12} /> Human in the loop</span>
            <span><Check size={12} /> CPU only</span>
          </div>
        </div>

        <div className="hero-stage">
          <div className="device-3d">
            <RegistrationViewport />
          </div>
          <div className="float f-tl"><div className="float-inner card glass">
            <div className="float-k mono">PLANTED FAULTS CAUGHT</div>
            <div className="float-v"><span className="aurora-num">{caught}</span><span className="float-of"> / {planted}</span></div>
            <div className="float-s">synthetic self-test</div>
          </div></div>
          <div className="float f-tr"><div className="float-inner card glass">
            <div className="float-k mono">PER INSPECTION</div>
            <div className="float-v brand">{sec}<small> s</small></div>
          </div></div>
          <div className="float f-br"><div className="float-inner card glass">
            <div className="float-k mono">FALSE ALARMS</div>
            <div className="float-v" style={{ color: "var(--pass)" }}>{fa}<span className="float-of"> / {correct.toLocaleString()}</span></div>
          </div></div>
          <div className="float f-bl"><div className="float-inner card glass float-chip">
            <span className="badge" style={{ ["--c" as string]: "var(--fail)" }}>FAIL</span>
            <b className="mono">{ISSUE_TEXT["ORD-RAIL-1"]}</b>
            <span className="faint small">proof ›</span>
          </div></div>
        </div>
      </div>
    </section>
  );
}
