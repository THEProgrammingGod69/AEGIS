import { AnimatePresence, motion } from "framer-motion";
import {
  BarChart3, Cloud, Command, Cpu, FlaskConical, History, LayoutGrid, Microscope, PlayCircle, Puzzle, RefreshCw, ScanEye, UserCheck, Zap,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Brand } from "./Logo";
import { Seg } from "./ui";
import { STATIC } from "../lib/api";
import { pingEngine, setPreferLive, useEngine } from "../lib/cloud";
import { calm, fine, gsap } from "../lib/gsap";
import { blinkTo } from "../lib/transition";
import type { Health } from "../lib/types";

export const NAV = [
  { key: "", label: "Overview", icon: LayoutGrid },
  { key: "inspect", label: "Inspect", icon: ScanEye },
  { key: "review", label: "Review", icon: UserCheck },
  { key: "analytics", label: "Analytics", icon: BarChart3 },
  { key: "forge", label: "Fault Forge", icon: FlaskConical },
  { key: "lab", label: "Robustness", icon: Microscope },
  { key: "history", label: "History", icon: History },
  { key: "engine", label: "Engine", icon: Puzzle },
];

function EnginePill() {
  const e = useEngine();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (ev: MouseEvent) => !ref.current?.contains(ev.target as Node) && setOpen(false);
    window.addEventListener("mousedown", off);
    return () => window.removeEventListener("mousedown", off);
  }, [open]);
  const live = e.state === "ready" && e.preferLive;
  const c = !e.preferLive ? "var(--accent-3)" : e.state === "ready" ? "var(--pass)" : e.state === "checking" ? "var(--review)" : "var(--fail)";
  const text = !e.preferLive ? "Instant replay" : e.state === "ready" ? "Live cloud engine" : e.state === "checking" ? "Waking cloud engine…" : "Engine offline · replay";
  return (
    <div className="engine-pop-wrap" ref={ref}>
      <button className="status-pill clickable" onClick={() => setOpen(!open)} aria-expanded={open} title="Engine status and mode">
        <span className={`dot${live || e.state === "checking" ? " pulse" : ""}`} style={{ ["--c" as string]: c }} />
        {text}
        {live && e.health && <span className="hide-sm faint row" style={{ ["--gap" as string]: "5px" }}>· <Cloud size={13} /> {e.health.tesseract.version?.replace("tesseract ", "OCR ")}</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="engine-pop card" initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.16 }}>
            <div className="tiny faint mono" style={{ letterSpacing: ".12em" }}>INSPECTION ENGINE</div>
            <Seg value={e.preferLive ? "live" : "replay"} onChange={(v) => setPreferLive(v === "live")} options={[
              { value: "live", label: <><Zap /> Live engine</>, title: "Real inspections on the cloud engine: your photos, your drawings, any check set" },
              { value: "replay", label: <><PlayCircle /> Instant replay</>, title: "Replay inspections recorded from the same engine" },
            ]} />
            <div className="kv small">
              <span>Status</span>
              <b style={{ color: c }}>{e.state === "ready" ? "Online" : e.state === "checking" ? "Connecting…" : e.state === "off" ? "Not configured" : "Unreachable"}</b>
              <span>Where</span><b className="mono ellipsis" title={e.url}>{e.url.replace(/^https?:\/\//, "") || "n/a"}</b>
              {e.health && <><span>OCR</span><b className="mono">{e.health.tesseract.version} · {e.health.tesseract.backend ?? "CLI"}</b></>}
              {e.health && <><span>Compute</span><b className="mono">{e.health.cpu} vCPU · {e.health.workers} OCR lanes · no GPU</b></>}
              {e.latency != null && <><span>Round trip</span><b className="mono">{e.latency} ms</b></>}
            </div>
            <p className="tiny muted" style={{ margin: 0 }}>
              {e.preferLive
                ? "Live: every inspection runs the real Python engine in a container. Results stay in this browser; nothing is stored on the server."
                : "Replay: inspections recorded from the same engine, played back with their real stage timings. Uploads need the live engine."}
            </p>
            <button className="btn btn-sm" onClick={() => void pingEngine()} disabled={e.state === "checking"}><RefreshCw /> Check again</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** #25 nav: the active pill slides between links (GSAP) and a label scrambles on hover; links blink-transition (#2). */
function Nav({ active }: { active: string }) {
  const nav = useRef<HTMLElement>(null);
  const pill = useRef<HTMLSpanElement>(null);
  const first = useRef(true);

  useLayoutEffect(() => {
    const el = nav.current!;
    const place = (animate: boolean) => {
      const link = el.querySelector<HTMLElement>('.nav-item[aria-current="page"]');
      if (!link) return gsap.set(pill.current, { autoAlpha: 0 });
      const to = { x: link.offsetLeft, width: link.offsetWidth, autoAlpha: 1 };
      if (!animate || calm()) gsap.set(pill.current, to);
      else gsap.to(pill.current, { ...to, duration: 0.35, ease: "ee", overwrite: true });
    };
    place(!first.current);
    first.current = false;
    const ro = new ResizeObserver(() => place(false));
    ro.observe(el);
    return () => ro.disconnect();
  }, [active]);

  const scramble = (e: React.PointerEvent<HTMLAnchorElement>) => {
    if (calm() || !fine()) return;
    const label = e.currentTarget.querySelector<HTMLElement>("span");
    if (!label || label.offsetParent === null) return;
    gsap.to(label, { duration: 0.4, scrambleText: { text: label.dataset.label!, chars: "upperCase", speed: 0.6 }, overwrite: true });
  };

  return (
    <nav className="nav" aria-label="Main" ref={nav}>
      <span className="nav-pill" ref={pill} aria-hidden="true" />
      {NAV.map((n) => (
        <a key={n.key} href={`#/${n.key}`} className="nav-item" aria-current={active === n.key ? "page" : undefined} title={n.label}
          onPointerEnter={scramble}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            blinkTo(`#/${n.key}`, n.label);
          }}>
          <n.icon />
          <span data-label={n.label}>{n.label}</span>
        </a>
      ))}
    </nav>
  );
}

export function TopBar({ page, health, onPalette }: { page: string; health: Health | null; onPalette: () => void }) {
  const active = page === "run" || page === "work" ? "inspect" : page;
  const ok = health?.ok ?? health?.tesseract.ok;
  const label = !health ? "" : health.tesseract.ok ? "Engine ready" : health.ocr?.ok ? "Real-cabinet engine ready" : "Tesseract missing";
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Brand />
        <Nav active={active} />
        <div className="topbar-right">
          <button className="btn btn-sm btn-ghost palette-btn" onClick={onPalette} title="Command palette (Ctrl/⌘ K)">
            <Command /> <kbd>Ctrl K</kbd>
          </button>
          {STATIC ? <EnginePill /> : (
            <div className="status-pill" title={health ? (ok ? health.tesseract.version ?? "" : health.tesseract.error) : "Connecting…"}>
              <span className={`dot${ok ? " pulse" : ""}`} style={{ ["--c" as string]: health == null ? "var(--text-3)" : ok ? "var(--pass)" : "var(--fail)" }} />
              {health == null ? "Connecting…" : label}
              {health && (
                <span className="hide-sm faint row" style={{ ["--gap" as string]: "5px" }}>
                  · <Cpu size={13} /> {health.workers} OCR lanes
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
