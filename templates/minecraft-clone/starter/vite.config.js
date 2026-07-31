import { defineConfig } from "vite";

// A fixed toolchain for every model. Prescribing it is deliberate: otherwise part of the
// measured difference would be the build configuration rather than the actual task.
export default defineConfig({
  server: { host: "0.0.0.0", port: 5173 },
  preview: { host: "0.0.0.0", port: 4173 },
  build: { target: "es2022" },
});
