"""The dashboard module's `APIRouter` — one read-only route, the landing
page's own summary. Ported from `app/main.py`'s bare `GET /` route, but
mounted at `GET /dashboard` instead: the frontend's own root path (`/`)
already serves the SPA shell (`main.py`'s static-file mount), the same
`/foo` (this module's JSON) vs `/app/foo` (the React route) split every
other Phase 4 screen already follows — `/dashboard` is this screen's own
`/foo`.

Mounted into `app` with `get_current_session` required at the router
level, the same router-level dependency every module has carried since
Phase 1.14 — the direct equivalent of legacy's global `auth_gate`. No
write routes, so no `require_csrf_header` anywhere.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.engine import Connection

from ...db import get_connection
from ..auth.deps import get_current_session
from . import service

router = APIRouter(tags=["dashboard"], dependencies=[Depends(get_current_session)])


@router.get("/dashboard")
def dashboard(conn: Connection = Depends(get_connection)) -> dict:
    return service.dashboard_summary(conn)
