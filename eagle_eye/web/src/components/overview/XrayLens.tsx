/** #5 X-ray lens (storyboard C): a round lens floats over the cabinet photo; drag it and the GA drawing shows through
 *  (a CSS clip-path follows the Draggable). Within 30 px of an anchor it snaps (liveSnap) and a pill reads the part
 *  and its verdict; release with velocity and InertiaPlugin glides it, bounded to the photo. Uses the real recorded
 *  inspection of sample 01, so the lens shows the drawing exactly where the engine registered it. */
import { Draggable } from "gsap/Draggable";
import { InertiaPlugin } from "gsap/InertiaPlugin";
import { Hand } from "lucide-react";
import { useRef } from "react";
import { url } from "../../lib/api";
import { ScrollTrigger, calm, gsap, useGSAP } from "../../lib/gsap";
import { SHOW, SH, SW, TAG_FAULT, bb, isFailedTag, nearestItem, pts } from "../../lib/showcase";

gsap.registerPlugin(Draggable, InertiaPlugin);

const R = 64; // lens radius, px

const ITEM_CENTERS = SHOW.layout.map((l) => {
  const b = bb(l.quad);
  return { x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2 };
});

export function XrayLens() {
  const root = useRef<HTMLDivElement>(null);

  useGSAP(() => {
    const el = root.current!;
    const photo = el.querySelector<HTMLElement>(".xray-photo")!;
    const lens = el.querySelector<HTMLElement>(".lens")!;
    const drawing = el.querySelector<HTMLElement>(".xray-drawing")!;
    const pill = el.querySelector<HTMLElement>(".lens-pill")!;
    const k = () => photo.clientWidth / SW; // screen px per photo px

    const readout = (cx: number, cy: number) => {
      drawing.style.clipPath = `circle(${R - 3}px at ${cx}px ${cy}px)`;
      const s = k();
      const near = nearestItem(cx / s, cy / s);
      if (near && near.d * s < 46) {
        pill.textContent = near.fail ? `${near.tag} · FAIL · ${TAG_FAULT[near.tag] ?? "see proof"}` : `${near.tag} · OK`;
        pill.dataset.v = near.fail ? "fail" : "pass";
      } else {
        pill.textContent = "X-RAY";
        pill.dataset.v = "";
      }
    };

    const dock = () => ({ x: photo.clientWidth - 2 * R - 16, y: photo.clientHeight - 2 * R - 16 });
    gsap.set(lens, dock());
    readout(dock().x + R, dock().y + R);

    const [drag] = Draggable.create(lens, {
      bounds: photo,
      inertia: !calm(),
      onPress() { el.classList.add("active"); },
      onRelease() { if (!this.tween) el.classList.remove("active"); },
      onThrowComplete() { el.classList.remove("active"); },
      onDrag() { readout(this.x + R, this.y + R); },
      onThrowUpdate() { readout(this.x + R, this.y + R); },
      liveSnap: {
        points: (p: { x: number; y: number }) => {
          const s = k();
          let best = p;
          let bd = 30;
          for (const c of ITEM_CENTERS) {
            const q = { x: c.x * s - R, y: c.y * s - R };
            const d = Math.hypot(q.x - p.x, q.y - p.y);
            if (d < bd) { bd = d; best = q; }
          }
          return best;
        },
      },
    });

    // the demo glides the lens from its dock to the missing PS12, then hands it to you
    if (!calm()) {
      const target = SHOW.issues[0];
      const b = bb(target.quad);
      ScrollTrigger.create({
        trigger: el, start: "top 65%", once: true,
        onEnter: () => {
          const s = k();
          gsap.to(lens, {
            x: (b.x0 + b.x1) / 2 * s - R, y: (b.y0 + b.y1) / 2 * s - R, duration: 1.4, ease: "expo.inOut", delay: 0.2,
            onUpdate: () => {
              const x = Number(gsap.getProperty(lens, "x"));
              const y = Number(gsap.getProperty(lens, "y"));
              readout(x + R, y + R);
            },
            onComplete: () => void drag.update(),
          });
        },
      });
    }

    const ro = new ResizeObserver(() => {
      drag.applyBounds(photo);
      drag.update();
      readout(drag.x + R, drag.y + R);
    });
    ro.observe(photo);
    return () => ro.disconnect();
  }, { scope: root });

  return (
    <div className="xray" ref={root}>
      <div className="xray-photo device" style={{ aspectRatio: `${SW} / ${SH}` }} data-cursor="Drag">
        <img src={url.sample("01", 1100)} alt="Emerson's example cabinet" draggable={false} loading="lazy" />
        <div className="xray-drawing" aria-hidden="true">
          <svg viewBox={`0 0 ${SW} ${SH}`}>
            <polygon className="xd-bp" points={pts(SHOW.backplate)} />
            {SHOW.layout.map((l) => {
              const b = bb(l.quad);
              return (
                <g key={l.tag} className={isFailedTag(l.tag) ? "xd-item fail" : "xd-item"}>
                  <polygon points={pts(l.quad)} />
                  <text x={b.x0 + 14} y={b.y0 + 54}>{l.tag}</text>
                </g>
              );
            })}
          </svg>
        </div>
        <div className="lens" role="slider" aria-label="X-ray lens: drag to see the GA drawing under the photo" tabIndex={0}>
          <span className="lens-ring" />
          <span className="lens-pill mono">X-RAY</span>
        </div>
        <span className="xray-hint mono"><Hand size={13} /> drag the lens</span>
      </div>
    </div>
  );
}
