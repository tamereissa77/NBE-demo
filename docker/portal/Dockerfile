# NBE portal: React + Vite build, served as static files by Caddy (SPA fallback).
# Fonts are bundled by npm (@fontsource), so the running portal makes no external requests.
FROM node:20-slim AS build
# Mirror the repo layout so ../../brand resolves the same way as in local dev.
WORKDIR /repo/services/portal
COPY services/portal/package.json services/portal/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY brand /repo/brand
COPY services/portal ./
RUN npm run build

FROM caddy:2.11-alpine
COPY --from=build /repo/services/portal/dist /srv
COPY docker/portal/Caddyfile /etc/caddy/Caddyfile
EXPOSE 80
