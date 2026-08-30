"""App entrypoint — app factory + router mounting, per REBUILD.md §6's
tree comment. Real content as of Phase 1.14: every module built since
Phase 1.4 gets `include_router`'d here, for the first time — this file
itself owns none of their routes, same as it never has.

**The actual login/CSRF gate is *not* wired here as middleware, unlike
legacy's global `auth_gate`.** `modules/auth/deps.py`'s own docstring
already settled this back in Phase 1.11: `get_current_session`/
`require_csrf_header` are per-route `Depends(...)` — every router below
sets `get_current_session` at its own `APIRouter(dependencies=[...])`
level (the direct equivalent of legacy's blanket middleware, just
FastAPI-idiomatic instead of ASGI-idiomatic), and every write route
additionally depends on `require_csrf_header`. See each module's own
`router.py` docstring for the specifics of how Phase 1.14 wired it in
there. `modules/auth/router.py` itself carries no router-level
dependency — `/login` has to stay reachable with no session at all, and
its other four routes already spell out their own `Depends(...)` per
route.

**What legacy's `auth_gate` did that a per-route `Depends(...)` has no
natural place for: lazily materializing due schedules on every
authenticated request** (SPEC.md decision 9 — no task runner in this
deployment, so "auto-post on the date" happens inline instead of on a
cron). That one piece of `auth_gate` genuinely is cross-cutting in a way
no single module's router can own, so it's the one bit of real
middleware this file adds — seeing every request, gated on there being a
valid session, otherwise a no-op. See `advance_due_schedules`'s own
docstring below.

**Migrations are not run from here**, unlike legacy's `lifespan` calling
`run_migrations()`. REBUILD.md decision 5 makes Alembic a separate,
explicit step that runs *before* this process starts (the Dockerfile's
own `CMD`, or CI's own `alembic upgrade head` step) — see `db.py`'s own
docstring for why baking that into a lazy, cached `Engine` here would be
the wrong layer for it.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .analytics.router import router as analytics_router
from .config import get_settings
from .db import get_engine
from .json import JSONResponse, configure_decimal_encoding
from .modules.auth import service as auth_service
from .modules.auth.deps import SESSION_COOKIE
from .modules.auth.router import router as auth_router
from .modules.budget.router import router as budget_router
from .modules.entries.router import router as entries_router
from .modules.imports.router import router as imports_router
from .modules.reference.router import router as reference_router
from .modules.reports.router import router as reports_router
from .modules.scheduling import service as scheduling_service
from .modules.scheduling.router import router as scheduling_router
from .modules.staging.router import router as staging_router

# Process-wide, once, before the app serves anything — see json.py's own
# docstring for why this alone doesn't cover every response path (routes
# that explicitly build JSONResponse(...) need to import it from .json,
# not from fastapi.responses, to get the same fix).
configure_decimal_encoding()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ports legacy `lifespan`'s one remaining piece: seeding the first
    admin user from `POSTWARDEN_ADMIN_USER`/`_PASSWORD` if the deployment
    has none yet (`auth.service.bootstrap_admin_from_env`'s own docstring
    has the full reasoning — silently a no-op once any user exists, so
    it's safe to leave the env vars set across every redeploy). Opens its
    own connection/transaction directly against `get_engine()` rather
    than `db.get_connection()` — that dependency is generator-shaped for
    FastAPI's per-request injection, not meant to be driven by hand
    outside a request."""
    settings = get_settings()
    with get_engine().connect() as conn, conn.begin():
        auth_service.bootstrap_admin_from_env(
            conn, settings.postwarden_admin_user, settings.postwarden_admin_password)
    yield


app = FastAPI(title="PostWarden", lifespan=lifespan, default_response_class=JSONResponse)


@app.middleware("http")
async def advance_due_schedules(request: Request, call_next):
    """The one piece of legacy's global `auth_gate` middleware that
    doesn't fit a per-route `Depends(...)` — see this file's own
    docstring for why the session/CSRF gate itself isn't here. Ported
    close to verbatim: a cheap, almost-always-empty lookup on every
    request that carries a session cookie, swallowing any failure the
    same bare `except Exception: pass` legacy uses ("a failure here
    shouldn't take the app down"). Opens its own connection rather than
    going through `db.get_connection()` for the same reason `lifespan`
    above does — this runs outside any route's own request-scoped
    dependency graph. Silently does nothing for an anonymous request
    (no session to check) or a genuinely expired/invalid one (`get_
    session` returns `None`) — the route's own `get_current_session`
    dependency answers the actual 401 for that case, this middleware just
    doesn't duplicate the check."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with get_engine().connect() as conn, conn.begin():
            if auth_service.get_session(conn, token):
                try:
                    scheduling_service.materialize_due_schedules(conn)
                except Exception:
                    pass
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness check — no DB touch. Used by Phase 0's docker-compose bring-up."""
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(reports_router)
app.include_router(entries_router)
app.include_router(staging_router)
app.include_router(imports_router)
app.include_router(budget_router)
app.include_router(reference_router)
app.include_router(scheduling_router)
app.include_router(analytics_router)
