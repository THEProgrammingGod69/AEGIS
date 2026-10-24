import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { STATUS_COLOR, statusText } from "../lib/format";
import { useCountUp } from "../lib/hooks";
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

export function Count({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const v = useCountUp(value);
  return <>{v.toFixed(decimals)}</>;
}

export function Kpi({ value, label, note, color, suffix, decimals }: {
  value: number; label: string; note?: ReactNode; color?: string; suffix?: string; decimals?: number;
}) {
  return (
    <div className="kpi" style={{ ["--c" as string]: color ?? "var(--text)" }}>
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

export function Meter({ value, color }: { value: number; color?: string }) {
  return (
    <div className="meter" style={{ ["--c" as string]: color ?? "var(--accent)" }}>
      <motion.i initial={{ width: 0 }} animate={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
    </div>
  );
}

export function SectionHead({ eyebrow, title, sub }: { eyebrow: string; title: ReactNode; sub?: ReactNode }) {
  return (
    <motion.div className="section-head" initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-80px" }} transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}>
      <span className="eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {sub && <p>{sub}</p>}
    </motion.div>
  );
}

export function Reveal({ children, delay = 0, y = 16, className, style }: { children: ReactNode; delay?: number; y?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <motion.div className={className} style={style} initial={{ opacity: 0, y }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }} transition={{ duration: 0.6, delay, ease: [0.22, 1, 0.36, 1] }}>
      {children}
    </motion.div>
  );
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
            <motion.div key={t.id} className={`toast ${t.kind}`} initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.97 }}>
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
