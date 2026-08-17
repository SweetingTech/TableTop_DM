import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  base: command === "serve" ? "/" : "/static/v2/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/socket.io": { target: "http://127.0.0.1:8000", ws: true },
    },
  },
  build: {
    outDir: "../static/v2",
    emptyOutDir: true,
  },
}));
