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

## The typed API client

```bash
npm run generate:api
```

Regenerates `src/api/schema.ts` from the backend's own OpenAPI schema —
`openapi-typescript` turns every route, path/query param, and Pydantic
request body under `backend/src/postwarden/modules/*/router.py` +
`schemas.py` into TypeScript types, and `src/api/client.ts` wraps them in
an `openapi-fetch` client every screen imports instead of hand-rolling its
own `fetch(...)` calls. Needs the **backend's own Python environment
active** (same one `pytest` needs — `cd ../backend && pip install
-e ".[dev]"`, or the checked-in `backend/.venv`), not just Node: the first
half of the script (`backend/scripts/dump_openapi_schema.py`) imports
`postwarden.main` directly rather than requiring a live server — see that
script's own docstring for why no `DATABASE_URL`/Postgres/Docker is needed
either.

`src/api/schema.ts` is **committed**, not gitignored, even though it's
generated — the frontend-build stage of `backend/Dockerfile` runs on a
bare `node:22-slim` image with no Python at all, so nothing in that build
can regenerate it. Re-run `npm run generate:api` and commit the diff
whenever a backend route or request body changes; nothing enforces that
automatically today (`--check` exists for a future CI step if drift turns
out to be a real problem in practice, not added preemptively here). The
intermediate `openapi.json` this writes along the way is gitignored — it's
just plumbing between the two commands, not itself consumed by anything.

Response bodies mostly type as `{ [key: string]: unknown }`, not real
interfaces — `entries/schemas.py`'s own docstring already settled that
route responses stay plain dicts, deliberately, so there is nothing more
specific for the OpenAPI schema to describe yet. `--empty-objects-unknown`
(in the `generate:api` script) is what keeps that as `unknown` rather than
openapi-typescript's default `Record<string, never>`, which would
(incorrectly) type every response as an object with no keys at all.

One rough edge worth knowing about: `openapi-typescript`'s `package.json`
declares a `typescript@^5.x` peer dependency, and this project is on `~6.0.2`
(the current `create-vite` default) — installing it needed
`--legacy-peer-deps`. Nothing about how openapi-typescript actually runs
depends on the installed `typescript` version (it emits `.ts` syntax as
text; it doesn't invoke the TypeScript compiler API), so this is a stale
peer-range declaration on their end, not a real incompatibility — confirmed
by generating the real schema against this project's real routes above.
