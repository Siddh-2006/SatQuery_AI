import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Standard Vite + React config. Nothing SatQuery-specific lives here —
// see src/main.tsx for how mocking (MSW) gets switched on in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts:["44df-117-239-204-232.ngrok-free.app",],
  },
});
