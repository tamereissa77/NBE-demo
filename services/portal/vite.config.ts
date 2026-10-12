import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, proxy /api to a running gateway (make up) so the portal can be iterated on outside Docker.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // brand/ (logo, mark, theme.css, brand.json) is the active brand pack, served at /
  publicDir: "../../brand",
  server: { proxy: { "/api": "http://localhost:8200" } },
});
