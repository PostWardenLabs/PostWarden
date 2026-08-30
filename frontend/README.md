# PostWarden — frontend

The React + TypeScript SPA, per [`REBUILD.md`](../REBUILD.md) — scaffolded
via `npm create vite@latest -- --template react-ts`. See
[`REBUILD_STATUS.md`](../REBUILD_STATUS.md)'s Phase 2 section for what's
built and what's next; this file stays a short pointer, not a duplicate.

## Local dev

```bash
npm install
npm run dev
```

`vite.config.ts` proxies `/healthz` to `http://localhost:8001` (the
backend's own `docker-compose.yml` default port), so `npm run dev`'s live
page can reach a real backend without a CORS dance. Run the backend
separately — `cd ../backend && docker compose up -d --build` — for that
proxy to have something to talk to.

## Build

```bash
npm run build
```

Writes straight into `../backend/src/postwarden/static/` (not this
project's own `dist/`) — `main.py` serves that directory via FastAPI's
`StaticFiles` if it exists. A plain `uvicorn postwarden.main:app` picks up
a build with no extra wiring; `backend/Dockerfile`'s own multi-stage build
does the same thing inside a discarded Node build stage, so the final
image never installs Node at all.
