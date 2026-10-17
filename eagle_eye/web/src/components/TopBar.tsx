import { motion } from "framer-motion";
import { Cpu, FlaskConical, History, LayoutGrid, Puzzle, ScanEye } from "lucide-react";
import { Brand } from "./Logo";
import { STATIC } from "../lib/api";
import type { Health } from "../lib/types";

const NAV = [
  { key: "", label: "Overview", icon: LayoutGrid },
  { key: "inspect", label: "Inspect", icon: ScanEye },
  { key: "forge", label: "Fault Forge", icon: FlaskConical },
  { key: "history", label: "History", icon: History },
  { key: "engine", label: "Engine", icon: Puzzle },
];

export function TopBar({ page, health }: { page: string; health: Health | null }) {
  const active = page === "run" ? "inspect" : page;
  const ok = health?.tesseract.ok;
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Brand />
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className="nav-item" aria-current={active === n.key ? "page" : undefined}>
              {active === n.key && <motion.span layoutId="nav-pill" className="nav-pill" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <n.icon />
              <span>{n.label}</span>
            </a>
          ))}
        </nav>
        <div className="topbar-right">
          <div className="status-pill" title={health ? (ok ? health.tesseract.version ?? "" : health.tesseract.error) : "Connecting…"}>
            <span className={`dot${ok ? " pulse" : ""}`} style={{ ["--c" as string]: health == null ? "var(--text-3)" : ok ? "var(--pass)" : "var(--fail)" }} />
            {health == null ? "Connecting…" : STATIC ? "Showcase · recorded engine runs" : ok ? "Engine ready" : "Tesseract missing"}
            {health && !STATIC && (
              <span className="hide-sm faint row" style={{ ["--gap" as string]: "5px" }}>
                · <Cpu size={13} /> {health.workers} OCR lanes
              </span>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
