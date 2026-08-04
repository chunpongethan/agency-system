import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on 5173; proxy /api-less calls go straight to the FastAPI backend
// via VITE_API_URL (see src/api/client.ts). The build is static and served by
// nginx in Docker (Phase 5).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
  preview: {
    port: 5173,
    host: true,
  },
});
