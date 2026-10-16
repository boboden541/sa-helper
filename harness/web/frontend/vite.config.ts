import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-режим: npm run dev поднимает vite на 5173 и проксирует API/SSE
// на витрину-сервер (python3 harness/web/server.py --workspace ...).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:4040",
      "/events": { target: "http://127.0.0.1:4040", changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
