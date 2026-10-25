import { AnimatePresence, motion } from "framer-motion";
import {
  BarChart3, Cloud, Cpu, FlaskConical, History, LayoutGrid, Microscope, PlayCircle, Puzzle, RefreshCw, ScanEye, Search, UserCheck, Zap,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Brand } from "./Logo";
import { Seg } from "./ui";
import { STATIC } from "../lib/api";
import { pingEngine, setPreferLive, useEngine } from "../lib/cloud";
import { tone } from "../lib/format";
import { calm, fine, gsap, intro } from "../lib/gsap";
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

const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

/** Signal meter: four bars that breathe while the engine is live, sit low on replay and drop out when it is offline. */
function Signal({ level }: { level: "live" | "wait" | "replay" | "off" }) {
  return (
    <span className={`sig sig-${level}`} aria-hidden="true">
      <i /><i /><i /><i />
    </span>
  );
}

function EnginePill() {
  const e = useEngine();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (ev: MouseEvent) => !ref.current?.contains(ev.target as Node) && setOpen(false);
    const esc = (ev: KeyboardEvent) => ev.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", off);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("mousedown", off);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);
  const live = e.state === "ready" && e.preferLive;
  const c = !e.preferLive ? "var(--accent-3)" : e.state === "ready" ? "var(--pass)" : e.state === "checking" ? "var(--review)" : "var(--fail)";
  const text = !e.preferLive ? "Instant replay" : e.state === "ready" ? "Live engine" : e.state === "checking" ? "Waking engine…" : "Offline · replay";
  const level = !e.preferLive ? "replay" : e.state === "ready" ? "live" : e.state === "checking" ? "wait" : "off";
  return (
    <div className="engine-pop-wrap" ref={ref}>
      <button className="tb-status" onClick={() => setOpen(!open)} aria-expanded={open} title="Engine status and mode" style={tone(c)}>
        <Signal level={level} />
        <span className="tb-status-text">{text}</span>
        {live && e.latency != null && <span className="tb-status-ms mono">{e.latency} ms</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div className="engine-pop card" initial={{ opacity: 0, y: -8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98 }} transition={{ duration: 0.18 }}>
            <div className="tiny faint mono" style={{ letterSpacing: ".12em" }}>INSPECTION ENGINE</div>
            <Seg value={e.preferLive ? "live" : "replay"} onChange={(v) => setPreferLive(v === "live")} options={[
              { value: "live", label: <><Zap /> Live engine</>, title: "Real inspections on the cloud engine: your photos, your drawings, any check set" },
              { value: "replay", label: <><PlayCircle /> Instant replay</>, title: "Replay inspections recorded from the same engine" },
            ]} />
            <div className="kv small">
              <span>Status</span>
              <b style={{ color: c }}>{e.state === "ready" ? "Online" : e.state === "checking" ? "Connecting…" : e.state === "off" ? "Not configured" : "Unreachable"}</b>
              <span>Where</span><b className="mono ellipsis" title={e.url}>{e.url.replace(/^https?:\/\//, "") || "n/a"}</b>
              {e.health && <><span>OCR</span><b className="mono"><Cloud size={12} /> {e.health.tesseract.version} · {e.health.tesseract.backend ?? "CLI"}</b></>}
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

/** Viewfinder nav: numbered destinations; four focus brackets hunt to the page you pick and lock on (a short spread,
 *  then a snap), a faint ghost follows the pointer, and the bar's drawing ruler marks the active page underneath. */
function Nav({ active }: { active: string }) {
  const nav = useRef<HTMLElement>(null);
  const reticle = useRef<HTMLSpanElement>(null);
  const ghost = useRef<HTMLSpanElement>(null);
  const first = useRef(true);

  useLayoutEffect(() => {
    const el = nav.current!;
    const ret = reticle.current!;
    const mark = document.querySelector<HTMLElement>(".tb-mark");
    const place = (animate: boolean) => {
      const link = el.querySelector<HTMLElement>('.nav-item[aria-current="page"]');
      if (!link) {
        gsap.set([ret, mark], { autoAlpha: 0 });
        return;
      }
      const ruler = mark?.parentElement;
      const to = { x: link.offsetLeft, width: link.offsetWidth, autoAlpha: 1 };
      const mx = ruler ? link.getBoundingClientRect().left - ruler.getBoundingClientRect().left : 0;
      const markTo = { x: mx, width: link.offsetWidth, autoAlpha: 1 };
      if (!animate || calm()) {
        gsap.set(ret, { ...to, "--s": "0px" });
        if (mark) gsap.set(mark, markTo);
        return;
      }
      gsap.to(ret, { ...to, duration: 0.5, ease: "expo.out", overwrite: true });
      // focus hunt: the brackets open while they travel, then snap shut on the new page
      gsap.timeline()
        .to(ret, { "--s": "7px", duration: 0.16, ease: "power2.out" })
        .to(ret, { "--s": "0px", duration: 0.5, ease: "back.out(3.2)" });
      gsap.fromTo(ret.querySelector(".nav-flash"), { opacity: 0.55 }, { opacity: 0, duration: 0.6, delay: 0.32, ease: "power2.out" });
      if (mark) gsap.to(mark, { ...markTo, duration: 0.55, ease: "expo.out", overwrite: true });
    };
    place(!first.current);
    first.current = false;
    const ro = new ResizeObserver(() => place(false));
    ro.observe(el);
    return () => ro.disconnect();
  }, [active]);

  // the ghost follows the pointer between items
  useEffect(() => {
    if (calm() || !fine()) return;
    const g = ghost.current!;
    const gx = gsap.quickTo(g, "x", { duration: 0.32, ease: "power3" });
    const gw = gsap.quickTo(g, "width", { duration: 0.32, ease: "power3" });
    let shown = false;
    const over = (e: PointerEvent) => {
      const item = (e.target as HTMLElement).closest<HTMLElement>(".nav-item");
      if (!item) return;
      if (!shown) {
        gsap.set(g, { x: item.offsetLeft, width: item.offsetWidth });
        gsap.to(g, { autoAlpha: 1, duration: 0.2, overwrite: "auto" });
        shown = true;
      }
      gx(item.offsetLeft);
      gw(item.offsetWidth);
    };
    const leave = () => {
      shown = false;
      gsap.to(g, { autoAlpha: 0, duration: 0.25, overwrite: "auto" });
    };
    const el = nav.current!;
    el.addEventListener("pointerover", over);
    el.addEventListener("pointerleave", leave);
    return () => {
      el.removeEventListener("pointerover", over);
      el.removeEventListener("pointerleave", leave);
    };
  }, []);

  const scramble = (e: React.PointerEvent<HTMLAnchorElement>) => {
    if (calm() || !fine()) return;
    const label = e.currentTarget.querySelector<HTMLElement>(".nav-label");
    if (!label || label.offsetParent === null) return;
    gsap.to(label, { duration: 0.4, scrambleText: { text: label.dataset.label!, chars: "upperCase", speed: 0.6 }, overwrite: true });
  };

  return (
    <nav className="nav" aria-label="Main" ref={nav}>
      <span className="nav-ghost" ref={ghost} aria-hidden="true" />
      <span className="nav-reticle" ref={reticle} aria-hidden="true"><i /><i /><i /><i /><b className="nav-flash" /></span>
      {NAV.map((n, i) => (
        <a key={n.key} href={`#/${n.key}`} className="nav-item" aria-current={active === n.key ? "page" : undefined} title={n.label}
          onPointerEnter={scramble}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
            e.preventDefault();
            blinkTo(`#/${n.key}`, n.label);
          }}>
          <n.icon />
          <span className="nav-idx mono">{String(i + 1).padStart(2, "0")}</span>
          <span className="nav-label" data-label={n.label}>{n.label}</span>
        </a>
      ))}
    </nav>
  );
}

/** Command bar: brand, viewfinder nav, jump field, engine signal. Its bottom edge is a drawing ruler that fills
 *  with the aurora as the page scrolls (the reading progress) while a scan light sweeps along it. */
export function TopBar({ page, health, onPalette }: { page: string; health: Health | null; onPalette: () => void }) {
  const active = page === "run" || page === "work" ? "inspect" : page;
  const ok = health?.ok ?? health?.tesseract.ok;
  const label = !health ? "" : health.tesseract.ok ? "Engine ready" : health.ocr?.ok ? "Real-cabinet engine ready" : "Tesseract missing";
  const bar = useRef<HTMLElement>(null);
  const fill = useRef<HTMLSpanElement>(null);

  // scrolled state + reading progress on the ruler (one rAF per scroll burst; clip-path on a 5 px strip)
  useEffect(() => {
    const el = bar.current!;
    let raf = 0;
    let up = false;
    const tick = () => {
      raf = 0;
      const y = window.scrollY;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const p = max > 8 ? Math.min(1, y / max) : 0;
      if (fill.current) fill.current.style.clipPath = `inset(0 ${(100 - p * 100).toFixed(2)}% 0 0)`;
      if (up !== y > 8) el.classList.toggle("scrolled", (up = y > 8));
    };
    const on = () => void (raf ||= requestAnimationFrame(tick));
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on, { passive: true });
    window.addEventListener("hashchange", on);
    const ro = new ResizeObserver(on);
    ro.observe(document.body);
    tick();
    return () => {
      window.removeEventListener("scroll", on);
      window.removeEventListener("resize", on);
      window.removeEventListener("hashchange", on);
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, []);

  // pointer glow inside the bar
  useEffect(() => {
    if (calm() || !fine()) return;
    const el = bar.current!;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      el.style.setProperty("--gx", `${e.clientX - r.left}px`);
    };
    el.addEventListener("pointermove", move, { passive: true });
    return () => el.removeEventListener("pointermove", move);
  }, []);

  // entrance, once the opening (preloader + hero) hands over: items drop in, the ruler draws out from the centre
  useEffect(() => {
    if (calm()) return;
    const el = bar.current!;
    let done = false;
    const parts = el.querySelectorAll(".brand, .nav-item, .tb-search, .tb-right > *");
    gsap.set(parts, { autoAlpha: 0, y: -8 });
    gsap.set(el.querySelector(".tb-ruler"), { scaleX: 0 });
    void intro.then(() => {
      if (done) return;
      gsap.to(parts, { autoAlpha: 1, y: 0, duration: 0.6, stagger: 0.035, ease: "expo.out", clearProps: "transform,opacity,visibility" });
      gsap.to(el.querySelector(".tb-ruler"), { scaleX: 1, duration: 1.1, ease: "expo.inOut", delay: 0.1, clearProps: "transform" });
    });
    return () => {
      done = true;
    };
  }, []);

  return (
    <header className="topbar" ref={bar}>
      <span className="tb-glow" aria-hidden="true" />
      <div className="topbar-inner">
        <Brand />
        <Nav active={active} />
        <div className="tb-right">
          <button className="tb-search" onClick={onPalette} title={`Command palette (${MAC ? "⌘" : "Ctrl"} K)`}>
            <Search />
            <span className="tb-search-text">Jump to…</span>
            <kbd>{MAC ? "⌘" : "Ctrl"} K</kbd>
          </button>
          {STATIC ? <EnginePill /> : (
            <div className="tb-status" title={health ? (ok ? health.tesseract.version ?? "" : health.tesseract.error) : "Connecting…"}
              style={tone(health == null ? "var(--text-3)" : ok ? "var(--pass)" : "var(--fail)")}>
              <Signal level={health == null ? "wait" : ok ? "live" : "off"} />
              <span className="tb-status-text">{health == null ? "Connecting…" : label}</span>
              {health && <span className="tb-status-ms mono"><Cpu size={12} /> {health.workers}</span>}
            </div>
          )}
        </div>
      </div>
      <div className="tb-ruler" aria-hidden="true">
        <span className="tb-ticks" />
        <span className="tb-fill" ref={fill} />
        <span className="tb-scan" />
        <span className="tb-mark" />
      </div>
    </header>
  );
}
