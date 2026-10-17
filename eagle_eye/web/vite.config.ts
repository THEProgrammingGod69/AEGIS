import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to a running `python server.py`; `npm run build` writes web/dist,
// which server.py serves at http://127.0.0.1:8000.
// `npm run build:static` builds the hosted showcase (recorded runs from export_static.py) into web/dist-static.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "static" ? "./" : "/",
  publicDir: mode === "static" ? "static-public" : "public",
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: mode === "static" ? "dist-static" : "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
}));
