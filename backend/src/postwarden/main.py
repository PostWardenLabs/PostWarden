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

from fastapi import Depends, FastAPI, Request
from starlette.staticfiles import StaticFiles

from .analytics.router import router as analytics_router
from .config import Settings, get_settings
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


@app.get("/config")
def config(settings: Settings = Depends(get_settings)) -> dict:
    """Public, unauthenticated app metadata — Phase 3.1. Legacy never
    needed a route for this: `version`/`demo_banner`/`demo_user`/
    `demo_password` were plain Jinja globals, already in scope for
    every server-rendered template (`login.html`'s auth-brand corner
    and demo callout, `base.html`'s footer). A JSON SPA has nothing
    playing that role, so this is the same class of addition `GET /me`
    already is: dictated by the medium, not new business logic. Lives
    here rather than in a module for the same reason `/healthz` does —
    no DB touch, nothing worth a router/service/repository split for.

    Unauthenticated on purpose: the login page itself is the main
    caller, before any session exists.

    `demo_user`/`demo_password` are only ever included when
    `demo_banner` is true — this is a real, security-relevant departure
    from just mirroring the Jinja globals' own always-populated dict:
    those globals are always set server-side, but Jinja's own `{% if
    demo_banner %}` guard means legacy only ever put them in an actual
    HTTP response when a visitor was really looking at a demo instance.
    A JSON body has no equivalent of a template conditionally omitting
    a value from its own rendered output, so that conditional has to be
    made explicit here — the alternative would leak a real instance's
    admin password to any unauthenticated caller of this route whenever
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

# The built frontend (REBUILD_STATUS.md Phase 2.1) — mounted last and only
# if it exists, both deliberately.
#
# **Last**: a Mount is matched by prefix, and Starlette tries routes in
# registration order — every module's router above claims its own exact
# path(s) first, so this only ever answers a request none of them did.
# That matters concretely here: several of those routers already own a
# path a client-side route will eventually want too (`GET /entries` is the
# Journal's own JSON data route today; a future React Router path at the
# same literal `/entries` would never reach this mount, the API answers
# first). Deep-link/refresh support for the SPA's own client-side routes is
# a real gap this phase does not close — there is no router to wire it for
# yet (`REBUILD_STATUS.md` Phase 2.4/3), and closing it means deciding how
# the app-shell HTML and the JSON API stop sharing a path at all, not
# something to improvise here. `html=True` below covers what Phase 2.1
# actually needs: `/` itself, and every hashed `/assets/...` file Vite's
# own build produces.
#
# **Only if it exists**: `postwarden_static_dir` (`config.py`) is not
# required to be there — a backend-only checkout (CI, any module's own test
# suite, a developer who hasn't run `npm run build` yet) never had this
# directory before this phase and stays unaffected; the 523 existing tests
# assert nothing about `/` or `/assets/*`.
_static_dir = get_settings().postwarden_static_dir
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="frontend")
