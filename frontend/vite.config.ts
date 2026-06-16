import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the backend and the auth service so the SPA
// can use same-origin relative paths.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/v1/user-management": "http://localhost:8001",
      "/api": "http://localhost:8000",
    },
  },
});
