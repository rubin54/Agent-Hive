import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // loadEnv statt process.env: So wirken Einstellungen aus .env.local auch in dieser
  // Datei. Beide Werte sind überschreibbar, falls die Standardports lokal belegt sind.
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_API_TARGET || "http://127.0.0.1:8000";
  const port = Number(env.PORT) || 5173;

  return {
    plugins: [react()],
    server: {
      port,
      // Das Frontend spricht immer relative /api-Pfade. Im Dev-Betrieb leitet Vite sie
      // an FastAPI weiter, im Produktivbetrieb liefert FastAPI beides von derselben
      // Herkunft aus — dadurch gibt es keine Basis-URL, die konfiguriert werden müsste.
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
