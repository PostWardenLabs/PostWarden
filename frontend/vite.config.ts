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
    // real backend without a CORS dance. Not meant to grow into a full API
    // proxy list by hand — see frontend/src/api/client.ts's own comment on
    // how the typed client actually reaches the backend in dev vs. prod.
    // Port 8000: docker-compose.yml's own APP_PORT default, now that the
    // backend runs at the repo root instead of a separate backend/
    // instance on its own port.
    proxy: {
      '/healthz': 'http://localhost:8000',
    },
  },
})
