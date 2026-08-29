"""App entrypoint.

Phase 0 scaffolding only: enough to prove the container builds, installs,
and serves a request. config.py/db.py wiring and real router mounting land
in Phase 1.2 and 1.14 respectively (REBUILD_STATUS.md) — this file is cut
down to "app factory + router mounting only" at that point, per REBUILD.md
§6's tree comment. It does not import config.py or db.py yet, on purpose:
those are still empty stubs too.
"""
from fastapi import FastAPI

app = FastAPI(title="PostWarden")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check — no DB touch. Used by Phase 0's docker-compose bring-up."""
    return {"status": "ok"}
