import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Builds straight into the backend package's own static/ directory
    // (backend/src/postwarden/static, per config.py's postwarden_static_dir
    // default) rather than this project's own dist/. Two things fall out
    // of that for free, both worth having: a plain local `uvicorn
    // postwarden.main:app` picks up a `npm run build` with zero wiring
    // (no separate "copy the build somewhere" step for local dev), and the
    // Dockerfile's multi-stage build (a Node build stage, discarded before
    // the final image) copies to the exact same relative path — one
    // convention, not two. See REBUILD_STATUS.md's Phase 2.1 write-up:
    // "no Node process is required at runtime" is the actual gate this
    // satisfies.
    outDir: '../backend/src/postwarden/static',
    emptyOutDir: true,
  },
  server: {
    // Dev-only convenience so `npm run dev`'s own live page can reach the
    // real backend without a CORS dance — proxies just the one route this
    // phase's own placeholder page calls. Not meant to grow into a full API
    // proxy list by hand; Phase 2.2's typed client is where a real answer
    // to "how does the dev server reach every backend route" belongs.
    proxy: {
      '/healthz': 'http://localhost:8001',
    },
  },
})
