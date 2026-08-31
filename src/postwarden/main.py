"""App entrypoint — app factory + router mounting. This file owns no
module's routes; every router below is built elsewhere and `include_
router`'d in here.

**The login/CSRF gate is not wired here as middleware.**
`get_current_session`/`require_csrf_header` (`modules/auth/deps.py`) are
per-route `Depends(...)` instead: every router below sets `get_current_
session` at its own `APIRouter(dependencies=[...])` level, and every
write route additionally depends on `require_csrf_header`. See each
module's own `router.py` docstring for the specifics. `modules/auth/
router.py` itself carries no router-level dependency — `/login` has to
stay reachable with no session at all, and its other routes already
spell out their own `Depends(...)` per route.

**One thing doesn't fit a per-route dependency: lazily materializing due
schedules on every authenticated request** (SPEC.md decision 9 — no task
runner in this deployment, so "auto-post on the date" happens inline
instead of on a cron). That's genuinely cross-cutting in a way no single
module's router can own, so it's the one bit of real middleware this
file adds — seeing every request, gated on there being a valid session,
otherwise a no-op. See `advance_due_schedules`'s own docstring below.

**Migrations are not run from here.** Alembic is a separate, explicit
step that runs *before* this process starts (the Dockerfile's own `CMD`,
or CI's own `alembic upgrade head` step) — see `db.py`'s own docstring
for why baking that into a lazy, cached `Engine` here would be the wrong
layer for it.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from .analytics.router import router as analytics_router
from .config import Settings, get_settings
from .db import get_engine
from .json import JSONResponse, configure_decimal_encoding
from .modules.auth import service as auth_service
from .modules.auth.deps import SESSION_COOKIE
from .modules.auth.router import router as auth_router
from .modules.budget.router import router as budget_router
from .modules.dashboard.router import router as dashboard_router
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
    """Seeds the first admin user from `POSTWARDEN_ADMIN_USER`/
    `_PASSWORD` if the deployment has none yet
    (`auth.service.bootstrap_admin_from_env`'s own docstring has the
    full reasoning — silently a no-op once any user exists, so it's safe
    to leave the env vars set across every redeploy). Opens its own
    connection/transaction directly against `get_engine()` rather than
    `db.get_connection()` — that dependency is generator-shaped for
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
    """The one piece of the login gate that doesn't fit a per-route
    `Depends(...)` — see this file's own docstring for why the session/
    CSRF gate itself isn't here. A cheap, almost-always-empty lookup on
    every request that carries a session cookie, swallowing any failure
    on purpose (`except Exception: pass` — a failure here shouldn't take
    the app down). Opens its own connection rather than going through
    `db.get_connection()` for the same reason `lifespan` above does —
    this runs outside any route's own request-scoped dependency graph.
    Silently does nothing for an anonymous request (no session to check)
    or a genuinely expired/invalid one (`get_session` returns `None`) —
    the route's own `get_current_session` dependency answers the actual
    401 for that case, this middleware just doesn't duplicate the
    check."""
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
    """Liveness check — no DB touch."""
    return {"status": "ok"}


@app.get("/config")
def config(settings: Settings = Depends(get_settings)) -> dict:
    """Public, unauthenticated app metadata — the login page (before any
    session exists) is the main caller, for the footer's version string
    and the demo-instance banner/callout. Lives here rather than in a
    module for the same reason `/healthz` does — no DB touch, nothing
    worth a router/service/repository split for.

    `demo_user`/`demo_password` are only ever included when
    `demo_banner` is true — a real, security-relevant conditional, not
    incidental: leaving it out would leak a real instance's admin
    password to any unauthenticated caller of this route whenever
    `POSTWARDEN_ADMIN_PASSWORD` happens to be set (every Docker
    deployment's own bootstrap-admin convenience, not just demo's),
    regardless of `POSTWARDEN_DEMO_MODE`."""
    try:
        version = settings.postwarden_version_file.read_text().strip()
    except OSError:
        # Same tolerated-absence shape as `postwarden_static_dir` below:
        # a backend-only checkout, or an image built without `COPY
        # VERSION .`, shouldn't 500 this route over a missing footer
        # string.
        version = ""
    return {
        "version": version,
        "demo_banner": settings.postwarden_demo_mode,
        "demo_user": settings.postwarden_admin_user if settings.postwarden_demo_mode else None,
        "demo_password": settings.postwarden_admin_password if settings.postwarden_demo_mode else None,
    }


app.include_router(auth_router)
app.include_router(reports_router)
app.include_router(entries_router)
app.include_router(staging_router)
app.include_router(imports_router)
app.include_router(budget_router)
app.include_router(reference_router)
app.include_router(scheduling_router)
app.include_router(analytics_router)
app.include_router(dashboard_router)

# The built frontend — mounted last and only if it exists, both
# deliberately.
#
# **Last**: a Mount is matched by prefix, and Starlette tries routes in
# registration order — every module's router above claims its own exact
# path(s) first, so this only ever answers a request none of them did.
# That matters concretely here: several of those routers already own a
# path a client-side route will eventually want too (`GET /entries` is the
# Journal's own JSON data route). `html=True` below covers `/` itself
# and every hashed `/assets/...` file Vite's own build produces.
#
# **Only if it exists**: `postwarden_static_dir` (`config.py`) is not
# required to be there — a backend-only checkout (CI, any module's own
# test suite, a developer who hasn't run `npm run build` yet) is
# unaffected; the test suite asserts nothing about `/` or `/assets/*`.
#
# **`/app/*`, not `/api/*`, is the SPA's own namespace.** The obvious-
# looking fix — prefixing every data route with `/api` — turns out to be
# wrong once checked against the routes that exist: `analytics/router.py`
# already owns literal `/api/accounts`, `/api/entries`, `/api/trial-
# balance`, etc. as a real, external, already-documented contract — the
# Connect BI feature's `.pbids` files point Power BI at those exact URLs.
# Prefixing `modules/entries/`'s own `/entries` the same way would land
# it at `/api/entries` too, colliding with analytics' route of the same
# name, which is a completely different thing (a flat BI-consumer mirror
# vs. the Journal's own filter/paginate endpoint) — not a cosmetic clash,
# a real routing conflict. Renaming analytics' own paths instead was
# rejected too: that's a real, shipped integration point (a `.pbids` file
# a Power BI user has already saved somewhere points at today's URL), not
# internal plumbing free to move.
#
# So the SPA's own client-side routes live under `/app/*` instead — a
# namespace no module router has ever used. Zero backend routers changed:
# every module keeps its own bare path exactly as it already was,
# `analytics/router.py` included. The frontend's own `main.tsx` wraps
# everything in a `BrowserRouter`; `Sidebar`'s Tags link points at
# `/app/tags`, not `/tags` (which stays the JSON API's own path, still
# 401-gated, still answering a list of tags, never HTML).
#
# The two routes below are what actually close the deep-link gap: a direct
# browser navigation or refresh at `/app/tags` has no `index.html` file at
# that path for `StaticFiles(html=True)` to find (it only resolves
# `index.html` for a literal directory, not an arbitrary client-route
# path), so without them it would 404 instead of loading the SPA that's
# supposed to then let React Router take over client-side. Registered
# ahead of the catch-all mount (order matters, per "Last" above) and, like
# the mount itself, only if `_static_dir` actually has something to serve.
_static_dir = get_settings().postwarden_static_dir
_index_html = _static_dir / "index.html"


def _spa_index_response() -> FileResponse:
    """Split out of `spa_shell` below so it's callable directly from a
    test with no dependency on whether `_static_dir` existed at import
    time — its branching logic (missing file -> 404, not a 500) is
    cheap to cover directly."""
    if not _index_html.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(_index_html)


if _static_dir.is_dir():

    @app.get("/app")
    @app.get("/app/{path:path}")
    def spa_shell(path: str = "") -> FileResponse:
        """Serves the same `index.html` every other SPA entry point does —
        `path` itself is never inspected; React Router reads the real
        browser URL directly once the bundle loads, this route's only job
        is making sure that bundle actually gets served for a URL no
        static file on disk matches literally."""
        return _spa_index_response()

    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")
