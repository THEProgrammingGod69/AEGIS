import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { STATIC } from "./lib/api";
import { startKeepAlive } from "./lib/cloud";
import { registerServiceWorker } from "./lib/pwa";
import { loadStatic } from "./lib/static";
import "./styles/base.css";
import "./styles/ui.css";
import "./styles/pages.css";
import "./styles/round3.css";
import "./styles/motion.css";
import "./styles/overview.css";
import "./styles/topbar.css";
import "./styles/flair.css";

const mount = () =>
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );

if (STATIC) {
  startKeepAlive();                     // wake the cloud engine while the console loads
  registerServiceWorker();              // installable app + offline fallback (hosted production build only)
  loadStatic().then(mount, (e) => { document.body.textContent = `Could not load the console data: ${e}`; });
}
else mount();
