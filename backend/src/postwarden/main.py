"""App entrypoint.

config.py, db.py and json.py got real content in Phase 1.2/1.3; this file
still hasn't — real router mounting is Phase 1.14 (REBUILD_STATUS.md),
once there are routers under modules/ to mount. It stays "app factory
only" until then, per REBUILD.md §6's tree comment. /healthz deliberately
still doesn't touch the database (see its own docstring); a DB-touching
readiness check can be added alongside the first real module if one turns
out to be needed.
"""
from fastapi import FastAPI

from .json import JSONResponse, configure_decimal_encoding

# Process-wide, once, before the app serves anything — see json.py's own
# docstring for why this alone doesn't cover every response path (routes
# that explicitly build JSONResponse(...) need to import it from .json,
# not from fastapi.responses, to get the same fix).
configure_decimal_encoding()

app = FastAPI(title="PostWarden", default_response_class=JSONResponse)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check — no DB touch. Used by Phase 0's docker-compose bring-up."""
    return {"status": "ok"}
