import { AnimatePresence, motion } from "framer-motion";
import { ClipboardList, FlaskConical, Mic, PlayCircle, ScanEye, Trash2, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Presenter } from "./components/Presenter";
import { NAV, TopBar } from "./components/TopBar";
import { ToastProvider } from "./components/ui";
import { STATIC, api } from "./lib/api";
import { setPreferLive, useEngine } from "./lib/cloud";
import { go, useRoute } from "./lib/router";
import type { Health } from "./lib/types";
import { Analytics } from "./pages/Analytics";
import { Engine } from "./pages/Engine";
import { Forge } from "./pages/Forge";
import { History } from "./pages/History";
import { Inspect } from "./pages/Inspect";
import { Lab } from "./pages/Lab";
import { Overview } from "./pages/Overview";
import { Review } from "./pages/Review";
import { Run } from "./pages/Run";
import { WorkOrder } from "./pages/WorkOrder";

const TITLES: Record<string, string> = {
  "": "Overview", inspect: "Inspect", run: "Inspection", work: "Work order", review: "Review station", analytics: "Analytics",
  forge: "Fault Forge", lab: "Robustness Lab", history: "History", engine: "Engine",
};

export function App() {
  const route = useRoute();
  const eng = useEngine();
  const [health, setHealth] = useState<Health | null>(null);
  const [palette, setPalette] = useState(false);
  const [presenter, setPresenter] = useState(() => {
    try {
      return sessionStorage.getItem("ee_presenter") === "1" || new URLSearchParams(location.search).has("present");
    } catch {
      return false;
    }
  });
  const page = route[0] ?? "";

  useEffect(() => {
    let alive = true;
    const poll = () => api.health().then((h) => alive && setHealth(h)).catch(() => alive && setHealth(null));
    poll();
    const id = setInterval(poll, 15000);
    return () => { alive = false; clearInterval(id); };
  }, [eng.state, eng.preferLive]);

  useEffect(() => {
    document.title = `EAGLE EYE · ${TITLES[page] ?? "Cabinet QC"}`;
  }, [page]);

  useEffect(() => {
    try {
      sessionStorage.setItem("ee_presenter", presenter ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [presenter]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((x) => !x);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const commands = useMemo<Command[]>(() => {
    const latest = async (work = false) => {
      const r = (await api.runs(50)).find((m) => m.source !== "forge") ?? (await api.runs(1))[0];
      if (r) go(`${work ? "work" : "run"}/${r.id}`);
    };
    const c: Command[] = [
      { id: "demo", group: "Demo", label: "Run the live demo (sample 01)", hint: "4 planted faults", icon: <PlayCircle />, keywords: "start inspect", run: () => go("inspect/demo") },
      ...["02", "03", "04", "05"].map((s) => ({ id: `s${s}`, group: "Demo", label: `Inspect sample ${s}`, icon: <ScanEye />, run: () => go(`inspect/run/${s}`) })),
      { id: "forge", group: "Demo", label: "Forge and inspect an unseen cabinet", icon: <FlaskConical />, keywords: "fault forge random", run: () => go("forge/run") },
      { id: "latest", group: "Demo", label: "Open the latest inspection", icon: <ScanEye />, run: () => void latest() },
      { id: "wo", group: "Demo", label: "Work order for the latest inspection", icon: <ClipboardList />, keywords: "technician fix print", run: () => void latest(true) },
      { id: "present", group: "Demo", label: presenter ? "Hide presenter mode" : "Start presenter mode", hint: "demo script", icon: <Mic />, keywords: "tour script pitch", run: () => setPresenter((x) => !x) },
      ...NAV.map((n) => ({ id: `nav-${n.key}`, group: "Go to", label: n.label, icon: <n.icon />, run: () => go(n.key) })),
    ];
    if (STATIC)
      c.push({ id: "mode", group: "Engine", label: eng.preferLive ? "Switch to instant replay (recorded runs)" : "Switch to the live cloud engine", icon: <Zap />, run: () => setPreferLive(!eng.preferLive) });
    c.push({ id: "clear", group: "Engine", label: "Clear history on this device", icon: <Trash2 />, keywords: "delete reset", run: () => go("history") });
    return c;
  }, [presenter, eng.preferLive]);

  let view: JSX.Element;
  if (page === "inspect") view = <Inspect autoDemo={route[1] === "demo"} autoSample={route[1] === "run" ? route[2] ?? null : null} />;
  else if (page === "run" && route[1]) view = <Run id={route[1]} />;
  else if (page === "work" && route[1]) view = <WorkOrder id={route[1]} />;
  else if (page === "review") view = <Review />;
  else if (page === "analytics") view = <Analytics />;
  else if (page === "forge") view = <Forge auto={route[1] === "run"} />;
  else if (page === "lab") view = <Lab />;
  else if (page === "history") view = <History />;
  else if (page === "engine") view = <Engine />;
  else view = <div className="main"><Overview onPresent={() => setPresenter(true)} /></div>;

  return (
    <ToastProvider>
      <TopBar page={page} health={health} onPalette={() => setPalette(true)} />
      {!STATIC && health && !health.tesseract.ok && (
        <div className="setup-warn">
          Tesseract OCR was not found, so inspections cannot run. Install it (Windows: UB-Mannheim installer · macOS: <code>brew install tesseract</code> · Linux: <code>apt install tesseract-ocr</code>) or set <code>TESSERACT_CMD</code>, then restart <code>python server.py</code>.
        </div>
      )}
      <AnimatePresence mode="wait">
        <motion.main key={page + (route[1] ?? "")} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}>
          <ErrorBoundary resetKey={route.join("/")}>{view}</ErrorBoundary>
        </motion.main>
      </AnimatePresence>
      <footer className="footer">
        <div className="footer-inner">
          <span>EAGLE EYE · Team ENIGMA (Arya Ambekar, Arnav Sirse) · VIT Code_Apex 3.0 · Emerson Track 1</span>
          <span>Drawing-first verification · FAIL only when evidence agrees · CPU only · <button className="linkish" onClick={() => setPalette(true)}>Ctrl K</button></span>
        </div>
      </footer>
      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
      <Presenter open={presenter} onClose={() => setPresenter(false)} />
    </ToastProvider>
  );
}
