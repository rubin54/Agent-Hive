import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // loadEnv rather than process.env: settings from .env.local take effect in this file
  // too. Both values are overridable in case the default ports are taken locally.
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_TARGET || "http://127.0.0.1:8000";
  const port = Number(env.PORT) || 5173;

  return {
    plugins: [react()],
    server: {
      port,
      // The frontend always speaks relative /api paths. In development Vite proxies them
      // to FastAPI; in production FastAPI serves both from the same origin — so there is no
      // base URL that needs configuring.
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          // ws: the live run view speaks WebSocket over the same /api prefix. Without this
          // the upgrade request is proxied as plain HTTP and the stream never connects.
          ws: true,
        },
      },
    },
  };
});
