import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { STATUS_COLOR, statusText } from "../lib/format";
import { ScrollTrigger, SplitText, calm, gsap, useGSAP } from "../lib/gsap";
import type { Status } from "../lib/types";

export function StatusBadge({ s, lg, label }: { s: Status | "HOLD"; lg?: boolean; label?: string }) {
  return (
    <span className={`badge${lg ? " lg" : ""}`} style={{ ["--c" as string]: STATUS_COLOR[s] }}>
      {label ?? statusText(s)}
    </span>
  );
}

export function Marker({ n, s, lg }: { n: number | string; s: Status; lg?: boolean }) {
  return (
    <span className={`marker${lg ? " lg" : ""}`} style={{ ["--c" as string]: STATUS_COLOR[s] }}>
      {n}
    </span>
  );
}

/** #17 count-up: tweens the number straight into the DOM (no React render per frame), from 0 the first time it
 *  scrolls into view, then from the previous value whenever `value` changes. Calm shows the final value. */
export function Count({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const from = useRef(0);
  const seen = useRef(false);
  const fmt = (v: number) => v.toFixed(decimals);
  useGSAP(() => {
    const el = ref.current!;
    if (calm()) {
      el.textContent = fmt(value);
      from.current = value;
      return;
    }
    const o = { v: from.current };
    el.textContent = fmt(o.v);
    const run = () =>
      gsap.to(o, {
        v: value, duration: seen.current && from.current !== 0 ? 0.8 : 1.4, ease: "power3.out", overwrite: true,
        onUpdate: () => void (el.textContent = fmt(o.v)),
        onComplete: () => void (from.current = value),
      });
    if (seen.current) run();
    else ScrollTrigger.create({ trigger: el, start: "top 95%", once: true, onEnter: () => { seen.current = true; run(); } });
  }, { dependencies: [value, decimals] });
  return <span ref={ref} className="tnum" />;
}

export function Kpi({ value, label, note, color, suffix, decimals }: {
  value: number; label: string; note?: ReactNode; color?: string; suffix?: string; decimals?: number;
}) {
  return (
    <div className="kpi" data-spotlight="" style={{ ["--c" as string]: color ?? "var(--text)" }}>
      <div className="kpi-value">
        <Count value={value} decimals={decimals} />
        {suffix && <span style={{ fontSize: "0.55em", marginLeft: 3, opacity: 0.8 }}>{suffix}</span>}
      </div>
      <div className="kpi-label">{label}</div>
      {note && <div className="kpi-note">{note}</div>}
    </div>
  );
}

export function Switch({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" className="row" style={{ ["--gap" as string]: "9px" }} onClick={() => onChange(!on)}>
      <span className="switch" role="switch" aria-checked={on} />
      {label && <span className="small muted">{label}</span>}
    </button>
  );
}

export function Seg<T extends string | number>({ value, options, onChange }: {
  value: T; options: { value: T; label: ReactNode; title?: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="seg" role="group">
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} title={o.title} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Bar that grows from its left edge (#38 family): scaleX only, compositor-friendly. */
export function Meter({ value, color }: { value: number; color?: string }) {
  const ref = useRef<HTMLElement>(null);
  const w = Math.max(0.02, Math.min(1, value));
  useGSAP(() => {
    if (calm()) return;
    gsap.fromTo(ref.current, { scaleX: 0 }, { scaleX: 1, duration: 0.8, ease: "expo.out" });
  }, { dependencies: [w] });
  return (
    <div className="meter" style={{ ["--c" as string]: color ?? "var(--accent)" }}>
      <i ref={ref} style={{ width: `${w * 100}%`, transformOrigin: "0 50%" }} />
    </div>
  );
}

/** #11 line-mask reveal: the title's lines slide up out of a mask as the section scrolls in. */
export function SectionHead({ eyebrow, title, sub, center }: { eyebrow: ReactNode; title: ReactNode; sub?: ReactNode; center?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (calm()) return;
    const root = ref.current!;
    const h = root.querySelector("h2")!;
    const rest = root.querySelectorAll(".eyebrow, p");
    gsap.from(rest, { autoAlpha: 0, y: 14, duration: 0.7, stagger: 0.12, ease: "expo.out", scrollTrigger: { trigger: root, start: "top 88%", once: true } });
    SplitText.create(h, {
      type: "lines", mask: "lines", autoSplit: true,
      onSplit: (self) => gsap.from(self.lines, { yPercent: 105, stagger: 0.08, duration: 0.9, ease: "expo.out", scrollTrigger: { trigger: h, start: "top 88%", once: true } }),
    });
  }, { scope: ref });
  return (
    <div ref={ref} className={`section-head${center ? " center" : ""}`}>
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {sub && <p>{sub}</p>}
    </div>
  );
}

/** Scroll-in reveal (the [data-reveal] batch, per element): rises 16 px and fades in once. */
export function Reveal({ children, delay = 0, y = 18, className, style, ...rest }: {
  children: ReactNode; delay?: number; y?: number; className?: string; style?: CSSProperties;
} & Record<`data-${string}`, string | undefined>) {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (calm()) return;
    gsap.from(ref.current, { y, autoAlpha: 0, duration: 0.85, delay, ease: "expo.out", scrollTrigger: { trigger: ref.current, start: "top 92%", once: true } });
  }, { scope: ref });
  return <div ref={ref} className={className} style={style} {...rest}>{children}</div>;
}

/* ---------------- toasts ---------------- */
interface Toast {
  id: number;
  kind: "ok" | "error";
  text: string;
}

const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 9000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        <AnimatePresence>
          {items.map((t) => (
            <motion.div key={t.id} className={`toast ${t.kind}`} initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.97 }} transition={{ type: "spring", stiffness: 420, damping: 30 }}>
              {t.kind === "error" ? <AlertTriangle /> : <CheckCircle2 />}
              <div className="grow">{t.text}</div>
              <button className="faint" onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))} aria-label="Dismiss">
                <X size={15} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}
