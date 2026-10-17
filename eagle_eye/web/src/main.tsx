import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { STATIC } from "./lib/api";
import { loadStatic } from "./lib/static";
import "./styles/base.css";
import "./styles/ui.css";
import "./styles/pages.css";

const mount = () =>
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );

if (STATIC) loadStatic().then(mount, (e) => { document.body.textContent = `Could not load the showcase data: ${e}`; });
else mount();
