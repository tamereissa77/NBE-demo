import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, proxy /api to a running gateway (make up) so the portal can be iterated on outside Docker.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // brand/ (logo, mark, theme.css, brand.json) is the active brand pack, served at /
  publicDir: "../../brand",
  server: {
    proxy: {
      // D5_URL points /api/d5 at a demo run directly with uvicorn (no gateway), e.g. http://127.0.0.1:8005
      ...(process.env.D5_URL
        ? { "/api/d5": { target: process.env.D5_URL, rewrite: (p: string) => p.replace(/^\/api\/d5/, "") } }
        : {}),
      ...(process.env.D3_URL
        ? { "/api/d3": { target: process.env.D3_URL, rewrite: (p: string) => p.replace(/^\/api\/d3/, "") } }
        : {}),
      "/api":"http://localhost:8200",
    },
  },
});
