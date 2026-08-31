"""The dashboard module's `APIRouter` — one read-only route, the landing
page's own summary. Mounted at `GET /dashboard`, not `/`: the frontend's
own root path (`/`) already serves the SPA shell (`main.py`'s
static-file mount), the same `/foo` (this module's JSON) vs `/app/foo`
(the React route) split every other screen follows — `/dashboard` is
this screen's own `/foo`.

`get_current_session` is required at the router level, the same
router-level dependency every module carries. No write routes, so no
`require_csrf_header` anywhere.
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
