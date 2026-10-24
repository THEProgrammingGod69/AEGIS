/** Overview story sections: #4 exploded inspection (pinned), #18 vision model vs EAGLE EYE strike-through,
 *  #19 values deck that fans out with Flip, #13 horizontal pinned pipeline with a MotionPath packet.
 *  Only one pinned section is active at a time; on narrow screens nothing pins. */
import { Flip } from "gsap/Flip";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { Bot, Eye, type LucideIcon } from "lucide-react";
import { useRef } from "react";
import { url } from "../../lib/api";
import { ScrollTrigger, calm, gsap, useGSAP } from "../../lib/gsap";
import { SHOW, SH, SW, bb, isFailedTag, pts } from "../../lib/showcase";

gsap.registerPlugin(Flip, MotionPathPlugin);

/* ---------------- #4 exploded inspection ---------------- */
const STEPS = [
  { k: "PHOTO", t: "The photo, as taken.", s: "Tilted, glared, cable clutter. EAGLE EYE never asks it an open question like “what's wrong here?”." },
  { k: "DRAWING", t: "The drawing, read with code.", s: `The vector GA becomes a closed list of ${SHOW.layout.length} expected items with exact boxes, registered onto the photo through ${SHOW.anchors.length} label and ferrule anchors.` },
  { k: "VERDICTS", t: "One narrow question per item.", s: `${SHOW.counts.PASS} PASS, ${SHOW.counts.FAIL} FAIL, each boxed with expected-vs-found proof. Then the layers lock back together: that's registration.` },
];

export function Exploded() {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    if (calm()) return;
    const mm = gsap.matchMedia(root.current!);
    mm.add({ wide: "(min-width: 900px)", narrow: "(max-width: 899.98px)" }, (ctx) => {
      const { wide } = ctx.conditions as { wide: boolean };
      const tl = gsap.timeline({
        scrollTrigger: wide
          ? { trigger: root.current, start: "top top", end: "+=2200", pin: true, scrub: 0.8, anticipatePin: 1 }
          : { trigger: ".ex-stage", start: "top 80%", end: "bottom 20%", scrub: 0.8 },
      });
      tl.to(".ex-stack", { rotationX: 55, rotationZ: -30, duration: 1 })
        .addLabel("explode")
        .to(".layer-photo", { z: -150, duration: 1 }, "explode")
        .to(".layer-verdicts", { z: 150, duration: 1 }, "explode")
        .fromTo(".layer-label", { opacity: 0, x: -24 }, { opacity: 1, x: 0, stagger: 0.12, duration: 0.4 }, "explode+=0.3")
        .fromTo(".ex-step", { opacity: 0.28, y: 16 }, { opacity: 1, y: 0, stagger: 0.32, duration: 0.4 }, "explode+=0.1")
        .to(".layer-label", { opacity: 0, duration: 0.3 }, "+=0.6")
        .to(".layer-photo, .layer-verdicts", { z: 0, duration: 0.6, ease: "power4.in" }, "<")
        .to(".ex-stack", { rotationX: 0, rotationZ: 0, duration: 0.6 }, "<")
        .fromTo(".layer-verdicts .vx-fail", { opacity: 0.2 }, { opacity: 1, duration: 0.08, repeat: 5, yoyo: true });
    });
  }, { scope: root });

  return (
    <section className="explode" id="story" ref={root}>
      <div className="explode-inner">
        <div className="ex-copy">
          <span className="eyebrow">How a photo becomes proof</span>
          <h2 className="display-l">Three layers. <span className="brand-ink">One registration.</span></h2>
          <ol className="ex-steps">
            {STEPS.map((x, i) => (
              <li key={x.k} className="ex-step">
                <span className="ex-n mono">0{i + 1} · {x.k}</span>
                <b>{x.t}</b>
                <p>{x.s}</p>
              </li>
            ))}
          </ol>
        </div>
        <div className="ex-stage" aria-hidden="true">
          <div className="ex-stack" style={{ aspectRatio: `${SW} / ${SH}` }}>
            <div className="ex-layer layer-photo">
              <img src={url.sample("01", 900)} alt="" draggable={false} loading="lazy" />
              <span className="layer-label mono">PHOTO</span>
            </div>
            <div className="ex-layer layer-drawing">
              <svg viewBox={`0 0 ${SW} ${SH}`}>
                <polygon className="exd-bp" points={pts(SHOW.backplate)} />
                {SHOW.layout.map((l) => <polygon key={l.tag} className="exd-box" points={pts(l.quad)} />)}
              </svg>
              <span className="layer-label mono">DRAWING</span>
            </div>
            <div className="ex-layer layer-verdicts">
              <svg viewBox={`0 0 ${SW} ${SH}`}>
                {SHOW.layout.filter((l) => !isFailedTag(l.tag)).map((l) => {
                  const b = bb(l.quad);
                  return <circle key={l.tag} className="vx-pass" cx={(b.x0 + b.x1) / 2} cy={(b.y0 + b.y1) / 2} r={26} />;
                })}
                {SHOW.issues.map((it) => {
                  const b = bb(it.quad);
                  return (
                    <g key={it.id} className="vx-fail">
                      <rect x={b.x0 - 14} y={b.y0 - 14} width={b.x1 - b.x0 + 28} height={b.y1 - b.y0 + 28} rx={12} />
                      <circle cx={b.x1 + 14} cy={b.y0 - 14} r={46} />
                      <text x={b.x1 + 14} y={b.y0 + 5} textAnchor="middle">{it.marker}</text>
                    </g>
                  );
                })}
              </svg>
              <span className="layer-label mono">VERDICTS</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------- #18 vision model vs EAGLE EYE ---------------- */
export function VsTable({ rows }: { rows: [string, string, string][] }) {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (calm()) return;
    gsap.from(".strike path", { drawSVG: 0, duration: 0.5, stagger: 0.15, ease: "power2.inOut", scrollTrigger: { trigger: root.current, start: "top 70%", once: true } });
    gsap.from(".vs-row", { opacity: 0, y: 12, stagger: 0.06, duration: 0.6, ease: "expo.out", scrollTrigger: { trigger: root.current, start: "top 80%", once: true } });
  }, { scope: root });
  return (
    <div className="card vs vs-table" ref={root} data-spotlight="">
      <div className="vs-head">
        <div />
        <div className="vs-col-h bad"><Bot size={16} /> Ask a vision model</div>
        <div className="vs-col-h good"><Eye size={16} /> EAGLE EYE, drawing-first</div>
      </div>
      {rows.map(([k, a, b]) => (
        <div key={k} className="vs-row">
          <div className="vs-k">{k}</div>
          <div className="vs-a">
            <span>
              {a}
              <svg className="strike" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
                <path d="M1,6 C20,3.5 38,7.5 56,4.8 S86,5.5 99,4.2" />
              </svg>
            </span>
          </div>
          <div className="vs-b">{b}</div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- #19 values deck (stacked → fanned grid with Flip) ---------------- */
export function ValuesDeck({ items }: { items: { icon: LucideIcon; title: string; body: string }[] }) {
  const root = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const deck = root.current!;
    if (calm()) return;
    deck.classList.add("stacked");
    const cards = gsap.utils.toArray<HTMLElement>(".value-card", deck);
    cards.forEach((c, i) => gsap.set(c, { rotation: (i - (cards.length - 1) / 2) * 3.5, y: i * -3 }));
    ScrollTrigger.create({
      trigger: deck, start: "top 72%", once: true,
      onEnter: () => {
        const state = Flip.getState(cards);
        deck.classList.remove("stacked");
        gsap.set(cards, { rotation: 0, y: 0 });
        Flip.from(state, { duration: 0.9, ease: "expo.out", stagger: 0.05, absolute: true, onComplete: () => void gsap.set(cards, { clearProps: "transform" }) });
      },
    });
  }, { scope: root });
  return (
    <div className="values" ref={root}>
      {items.map((x, i) => (
        <div key={x.title} className="card pad value-card idea" data-spotlight="" data-tilt="6">
          <div className="idea-n mono">{String(i + 1).padStart(2, "0")}</div>
          <div className="idea-icon"><x.icon /></div>
          <h3>{x.title}</h3>
          <p>{x.body}</p>
        </div>
      ))}
    </div>
  );
}

/* ---------------- #13 horizontal pinned pipeline + packet ---------------- */
export function PipelineScroll({ steps }: { steps: { n: number; icon: LucideIcon; t: string; s: string; hl?: boolean }[] }) {
  const root = useRef<HTMLElement>(null);
  useGSAP(() => {
    if (calm()) return;
    const mm = gsap.matchMedia(root.current!);
    mm.add("(min-width: 900px)", () => {
      const track = root.current!.querySelector<HTMLElement>(".pipe-track")!;
      const dist = () => track.scrollWidth - window.innerWidth;
      const scrollTween = gsap.to(track, {
        x: () => -dist(), ease: "none",
        scrollTrigger: { trigger: root.current, pin: true, scrub: 0.6, invalidateOnRefresh: true, start: "top top", end: () => "+=" + dist() },
      });
      gsap.utils.toArray<HTMLElement>(".stage-card", track).forEach((card) => {
        gsap.from(card.querySelectorAll(".stage-icon svg path, .stage-icon svg circle, .stage-icon svg rect, .stage-icon svg line, .stage-icon svg polyline"), {
          drawSVG: 0, ease: "none",
          scrollTrigger: { trigger: card, containerAnimation: scrollTween, start: "left 70%", end: "left 35%", scrub: true },
        });
        gsap.from(card, {
          opacity: 0.35, scale: 0.94, ease: "none",
          scrollTrigger: { trigger: card, containerAnimation: scrollTween, start: "left 95%", end: "left 60%", scrub: true },
        });
      });
      gsap.to(".packet", {
        ease: "none",
        motionPath: { path: ".wire-path", align: ".wire-path", alignOrigin: [0.5, 0.5] },
        scrollTrigger: { trigger: root.current, scrub: 0.6, start: "top top", end: () => "+=" + dist(), invalidateOnRefresh: true },
      });
    });
  }, { scope: root });

  return (
    <section className="pipe-section" ref={root}>
      <div className="pipe-track">
        <div className="pipe-intro">
          <span className="eyebrow">The pipeline</span>
          <h2 className="display-l">Every expected item is checked. A FAIL needs agreeing evidence.</h2>
          <p>Stages 1 to 3 build the evidence. Stage 4 is where false alarms are stopped. Keep scrolling.</p>
        </div>
        <svg className="wire" viewBox="0 0 2400 200" preserveAspectRatio="none" aria-hidden="true">
          <path className="wire-path" d="M0,100 C200,40 400,160 600,100 S1000,40 1200,100 S1600,160 1800,100 S2200,40 2400,100" />
        </svg>
        <i className="packet" aria-hidden="true" />
        {steps.map((p) => (
          <div key={p.n} className={`card stage-card${p.hl ? " hl aurora-border" : ""}`} data-spotlight="">
            <div className="row between">
              <span className="pipe-n mono">0{p.n}</span>
              {p.hl && <span className="badge" style={{ ["--c" as string]: "var(--brand)" }}>FALSE ALARMS STOP HERE</span>}
            </div>
            <div className="stage-icon"><p.icon /></div>
            <h3>{p.t}</h3>
            <p>{p.s}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
