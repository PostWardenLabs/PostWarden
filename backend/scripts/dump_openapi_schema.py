"""Prints `app.openapi()` as JSON to stdout — the one input `frontend/`'s
own `npm run generate:api` (see `frontend/README.md`) needs to produce a
typed client (REBUILD_STATUS.md Phase 2.2).

Deliberately just imports `postwarden.main` and calls `.openapi()`, not a
real server: FastAPI builds the schema from the route/Pydantic
declarations alone, and `db.get_engine()` is lazy (its own docstring) —
nothing here ever calls `.connect()`, so no `DATABASE_URL`, no live
Postgres, and no Docker are needed to run this. That matters concretely:
it's what lets this same script run inside the frontend-build stage of
`backend/Dockerfile` context... except it doesn't, on purpose — that
stage's base image (`node:22-slim`) has no Python at all. Generating the
client is a *developer* step, run once and committed (see `frontend/src/
api/schema.ts`'s own header comment), not a build-time step either
Docker stage repeats.

Run from `backend/` with its own environment active (same one `pytest`
already needs — `pip install -e ".[dev]"` per `.github/workflows/
backend-ci.yml`, or the checked-in `backend/.venv`):

    python scripts/dump_openapi_schema.py > ../frontend/openapi.json
"""
import json

from postwarden.main import app

print(json.dumps(app.openapi()))
