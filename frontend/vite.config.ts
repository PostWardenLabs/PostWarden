import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Builds straight into the backend package's own static/ directory
    // (src/postwarden/static, per config.py's postwarden_static_dir
    // default) rather than this project's own dist/. Two things fall out
    // of that for free, both worth having: a plain local `uvicorn
    // postwarden.main:app` picks up a `npm run build` with zero wiring
    // (no separate "copy the build somewhere" step for local dev), and the
    // Dockerfile's multi-stage build (a Node build stage, discarded before
    // the final image) copies to the exact same relative path — one
    // convention, not two. The gate this satisfies: no Node process is
    // required at runtime, only the static files it produced.
    outDir: '../src/postwarden/static',
    emptyOutDir: true,
  },
  server: {
    // Dev-only convenience so `npm run dev`'s own live page can reach the
    // real backend without a CORS dance — this is what makes
    // `api/client.ts`'s same-origin `baseUrl` true in dev, not just prod.
    // Port 8000: docker-compose.yml's own APP_PORT default, now that the
    // backend runs at the repo root instead of a separate backend/
    // instance on its own port.
    //
    // Every real API route lives at a bare top-level path (`/entries`,
    // `/login`, `/accounts`, `/reports/*`, ...) alongside the SPA, which
    // is mounted only under `/app` and `/app/{path}` (main.py). A single
    // `/healthz` entry here used to be all this proxied — silently stale
    // the moment a second route module was mounted, since nothing forced
    // this list to grow alongside main.py's own routers, and `npm run
    // dev` degraded to serving the SPA shell (or a bare 404) for every
    // other path with no error to notice. The regex below inverts that:
    // proxy anything that ISN'T the SPA (`/app`, `/app/*`, bare `/`),
    // vite's own internal/HMR paths (`/@...`, `/src/*`, `/node_modules/*`),
    // or a `public/` static asset (anything whose last path segment has
    // a file extension, e.g. `/favicon.svg`) — so a newly mounted backend
    // route is proxied automatically, with nothing here to remember to
    // update.
    proxy: {
      '^/(?!$|app(?:/|$)|@|src/|node_modules/)(?!.*\\.[^/]+$).*': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
