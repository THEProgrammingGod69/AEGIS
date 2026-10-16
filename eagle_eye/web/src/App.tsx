import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { TopBar } from "./components/TopBar";
import { ToastProvider } from "./components/ui";
import { api } from "./lib/api";
import { useRoute } from "./lib/router";
import type { Health } from "./lib/types";
import { Engine } from "./pages/Engine";
import { Forge } from "./pages/Forge";
import { History } from "./pages/History";
import { Inspect } from "./pages/Inspect";
import { Overview } from "./pages/Overview";
import { Run } from "./pages/Run";

export function App() {
  const route = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const page = route[0] ?? "";

  useEffect(() => {
    let alive = true;
    const poll = () => api.health().then((h) => alive && setHealth(h)).catch(() => alive && setHealth(null));
    poll();
    const id = setInterval(poll, 15000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    const titles: Record<string, string> = { "": "Overview", inspect: "Inspect", run: "Inspection", forge: "Fault Forge", history: "History", engine: "Engine" };
    document.title = `EAGLE EYE · ${titles[page] ?? "Cabinet QC"}`;
  }, [page]);

  let view: JSX.Element;
  if (page === "inspect") view = <Inspect autoDemo={route[1] === "demo"} />;
  else if (page === "run" && route[1]) view = <Run id={route[1]} />;
  else if (page === "forge") view = <Forge />;
  else if (page === "history") view = <History />;
  else if (page === "engine") view = <Engine />;
  else view = <div className="main"><Overview /></div>;

  return (
    <ToastProvider>
      <TopBar page={page} health={health} />
      {health && !health.tesseract.ok && (
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
          <span>Drawing-first verification · FAIL only when evidence agrees · runs locally on CPU</span>
        </div>
      </footer>
    </ToastProvider>
  );
}
