import { ClipboardList, FlaskConical, Gauge, Mic, PlayCircle, ScanEye, ScanLine, Trash2, Zap } from "lucide-react";
import { Suspense, lazy, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { CommandPalette, type Command } from "./components/CommandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Preloader } from "./components/Preloader";
import { Presenter } from "./components/Presenter";
import { NAV, TopBar } from "./components/TopBar";
import { ToastProvider } from "./components/ui";
import { STATIC, api } from "./lib/api";
import { setPreferLive, useEngine } from "./lib/cloud";
import { ScrollTrigger, SplitText, calm, gsap, introDone, setMotion, useGSAP } from "./lib/gsap";
import { installAmbient, installClickSpark, installInteractions, installXray, toggleXray } from "./lib/interactions";
import { go, useRoute } from "./lib/router";
import { blinkTo } from "./lib/transition";
import type { Health } from "./lib/types";
import { Overview } from "./pages/Overview";

// Every page but the Overview loads on demand (and is prefetched once the console is idle), so the first paint
// carries only the landing page and the motion core.
const pages = {
  inspect: () => import("./pages/Inspect"),
  run: () => import("./pages/Run"),
  work: () => import("./pages/WorkOrder"),
  review: () => import("./pages/Review"),
  analytics: () => import("./pages/Analytics"),
  forge: () => import("./pages/Forge"),
  lab: () => import("./pages/Lab"),
  history: () => import("./pages/History"),
  engine: () => import("./pages/Engine"),
};
const Inspect = lazy(() => pages.inspect().then((m) => ({ default: m.Inspect })));
const Run = lazy(() => pages.run().then((m) => ({ default: m.Run })));
const WorkOrder = lazy(() => pages.work().then((m) => ({ default: m.WorkOrder })));
const Review = lazy(() => pages.review().then((m) => ({ default: m.Review })));
const Analytics = lazy(() => pages.analytics().then((m) => ({ default: m.Analytics })));
const Forge = lazy(() => pages.forge().then((m) => ({ default: m.Forge })));
const Lab = lazy(() => pages.lab().then((m) => ({ default: m.Lab })));
const History = lazy(() => pages.history().then((m) => ({ default: m.History })));
const Engine = lazy(() => pages.engine().then((m) => ({ default: m.Engine })));

const TITLES: Record<string, string> = {
  "": "Overview", inspect: "Inspect", run: "Inspection", work: "Work order", review: "Review station", analytics: "Analytics",
  forge: "Fault Forge", lab: "Robustness Lab", history: "History", engine: "Engine",
};

const seen = () => {
  try {
    return sessionStorage.getItem("ee_seen") === "1";
  } catch {
    return true;
  }
};

/** #11 on every page: the page title's lines rise out of a mask, then its eyebrow and lead fade up. Sits inside
 *  Suspense, so it runs once the lazily loaded page has rendered. */
function PageMotion({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    if (calm()) return;
    const h = ref.current!.querySelector<HTMLElement>(".page-head h1");
    if (h) SplitText.create(h, {
      type: "lines", mask: "lines", autoSplit: true,
      onSplit: (self) => gsap.from(self.lines, { yPercent: 105, stagger: 0.08, duration: 0.9, ease: "expo.out", delay: 0.08 }),
    });
    const rest = ref.current!.querySelectorAll(".page-head .eyebrow, .page-head p");
    if (rest.length) gsap.from(rest, { y: 12, autoAlpha: 0, stagger: 0.08, duration: 0.7, ease: "expo.out", delay: 0.15 });
  }, { scope: ref });
  return <div ref={ref}>{children}</div>;
}

function PageFallback() {
  return (
    <div className="main">
      <div className="skeleton" style={{ height: 120, marginBottom: 18, maxWidth: 640 }} />
      <div className="skeleton" style={{ height: 520 }} />
    </div>
  );
}

export function App() {
  const route = useRoute();
  const eng = useEngine();
  const [health, setHealth] = useState<Health | null>(null);
  const [palette, setPalette] = useState(false);
  const [preload, setPreload] = useState(() => !calm() && !seen());
  const [presenter, setPresenter] = useState(() => {
    try {
      return sessionStorage.getItem("ee_presenter") === "1" || new URLSearchParams(location.search).has("present");
    } catch {
      return false;
    }
  });
  const page = route[0] ?? "";
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!preload) introDone();
    installInteractions();
    installAmbient();
    installXray();
    installClickSpark();
    // pinned sections measure after images and fonts settle
    const refresh = () => ScrollTrigger.refresh();
    window.addEventListener("load", refresh);
    void document.fonts?.ready.then(refresh);
    // warm the other pages once the console is idle
    const idle = (window as Window & { requestIdleCallback?: (f: () => void) => number }).requestIdleCallback ?? ((f: () => void) => window.setTimeout(f, 1500));
    idle(() => Object.values(pages).forEach((p) => void p().catch(() => {})));
    return () => window.removeEventListener("load", refresh);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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

  // a new page starts at its top, however it was reached (nav, palette, or a plain #/ link in a card)
  const routeKey = page + "/" + (route[1] ?? "");
  const firstRoute = useRef(true);
  useLayoutEffect(() => {
    if (firstRoute.current) { firstRoute.current = false; return; }
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [routeKey]);

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

  // the new page's content rises in (behind the opening lids when the blink transition is running)
  useGSAP(() => {
    if (calm() || !mainRef.current) return;
    gsap.fromTo(mainRef.current, { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.5, ease: "expo.out", clearProps: "transform,opacity,visibility" });
  }, { dependencies: [route.join("/")] });

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
      ...NAV.map((n) => ({ id: `nav-${n.key}`, group: "Go to", label: n.label, icon: <n.icon />, run: () => blinkTo(`#/${n.key}`, n.label) })),
      { id: "motion", group: "Display", label: calm() ? "Motion: Full" : "Motion: Calm", hint: calm() ? "now Calm" : "now Full", icon: <Gauge />, keywords: "animation reduce reduced projector stutter calm full", run: () => setMotion(calm() ? "full" : "calm") },
      { id: "xray", group: "Display", label: "X-ray: show the GA drawing on every photo", hint: "or press X", icon: <ScanLine />, keywords: "overlay drawing easter egg", run: () => void toggleXray() },
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
  else view = <Overview onPresent={() => setPresenter(true)} />;

  return (
    <ToastProvider>
      <TopBar page={page} health={health} onPalette={() => setPalette(true)} />
      {!STATIC && health && !health.tesseract.ok && (
        <div className="setup-warn">
          {health.ocr?.ok
            ? <>Tesseract OCR was not found: the demo cabinets (samples, Fault Forge) cannot run. Real drawing sets use PP-OCRv4 and work. </>
            : <>Tesseract OCR was not found, so inspections cannot run. </>}
          Install it (Windows: UB-Mannheim installer · macOS: <code>brew install tesseract</code> · Linux: <code>apt install tesseract-ocr</code>) or set <code>TESSERACT_CMD</code>, then restart <code>python server.py</code>.
        </div>
      )}
      <main key={page + (route[1] ?? "")} ref={mainRef}>
        <ErrorBoundary resetKey={route.join("/")}>
          <Suspense fallback={<PageFallback />}><PageMotion>{view}</PageMotion></Suspense>
        </ErrorBoundary>
      </main>
      <footer className="footer">
        <div className="footer-mark" aria-hidden="true">
          <span className="fm-outline">EAGLE EYE</span>
          <span className="fm-fill">EAGLE EYE</span>
          <span className="fm-beam" />
        </div>
        <div className="footer-inner">
          <span>EAGLE EYE · Team ENIGMA (Arya Ambekar, Arnav Sirse) · VIT Code_Apex 3.0 · Built for Emerson&apos;s Track 1 challenge</span>
          <span>Drawing-first verification · FAIL only when evidence agrees · CPU only · <button className="linkish" onClick={() => setPalette(true)}>Ctrl K</button> · press <kbd>X</kbd> for X-ray</span>
        </div>
      </footer>
      <div className="lids" aria-hidden="true">
        <div className="lid lid-top" />
        <div className="lid lid-bottom" />
        <div className="lid-label mono" />
      </div>
      {preload && <Preloader onDone={() => {
        try {
          sessionStorage.setItem("ee_seen", "1");
        } catch {
          /* ignore */
        }
        setPreload(false);
        introDone();
        ScrollTrigger.refresh();
      }} />}
      <CommandPalette open={palette} onClose={() => setPalette(false)} commands={commands} />
      <Presenter open={presenter} onClose={() => setPresenter(false)} />
    </ToastProvider>
  );
}
