/** Installable app: registers the service worker (static-public/sw.js) on the hosted production build only, so the
 *  local console (`python server.py`) and the dev server behave exactly as before. Once the worker is ready the page
 *  hands it the files it has already loaded, so a first visit stays available offline. */
import { STATIC } from "./api";

export function registerServiceWorker() {
  if (!STATIC || !import.meta.env.PROD || !("serviceWorker" in navigator) || !window.isSecureContext) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./sw.js")
      .then(() => navigator.serviceWorker.ready)
      .then((reg) => {
        // after the idle prefetch of the other pages, so their chunks are in the list too
        window.setTimeout(() => {
          const urls = performance.getEntriesByType("resource").map((r) => r.name).filter((u) => u.startsWith(location.origin));
          reg.active?.postMessage({ type: "warm", urls });
        }, 6000);
      })
      .catch(() => {
        /* no worker (private mode, blocked storage): the console simply stays online-only */
      });
  });
}
