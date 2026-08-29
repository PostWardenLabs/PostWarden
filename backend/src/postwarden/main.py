"""App entrypoint.

config.py and db.py got real content in Phase 1.2; this file still hasn't
— real router mounting is Phase 1.14 (REBUILD_STATUS.md), once there are
routers under modules/ to mount. It stays "app factory only" until then,
per REBUILD.md §6's tree comment. /healthz deliberately still doesn't touch
the database (see its own docstring); a DB-touching readiness check can be
added alongside the first real module if one turns out to be needed.
"""
from fastapi import FastAPI

app = FastAPI(title="PostWarden")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check — no DB touch. Used by Phase 0's docker-compose bring-up."""
    return {"status": "ok"}
