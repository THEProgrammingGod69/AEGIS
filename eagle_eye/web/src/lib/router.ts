import { useEffect, useState } from "react";

/** Minimal hash router: #/inspect, #/run/<id>, #/forge ... (works from any static host, no server rewrites). */
export function useRoute(): string[] {
  const read = () => (window.location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(path: string) {
  const h = "#/" + path.replace(/^\/+/, "");
  if (window.location.hash !== h) window.location.hash = h;
  window.scrollTo({ top: 0, behavior: "smooth" });
}
