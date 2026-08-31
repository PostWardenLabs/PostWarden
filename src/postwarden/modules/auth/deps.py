"""Reusable FastAPI dependencies — the pieces every other write module
`Depends(...)` on for session/CSRF checks.

**Why this module is meant to be imported directly, not forked, unlike
sibling business modules.** "A module should be deletable on its own"
is why `modules/staging/`, `/imports/`, `/scheduling/`, and `/budget/`
each fork a small copy of whatever helper they needed from an earlier
business module (`account_ids_by_code`, `check_deferred_constraints`, a
filter-fragment builder) rather than import it — those are siblings,
each one conceivably deletable without the others caring. Auth isn't a
sibling in that sense: every one of those modules already depends,
unconditionally, on there being a logged-in user at all. Forking
session-lookup/CSRF logic five times over would not preserve any real
independence — deleting `modules/auth/` while keeping any other module
means nothing can log in, full stop, whether or not the copy is
literally the same file. Importing it directly here is the honest
expression of that, the same way every module already imports
`db.get_connection`/`errors.pg_message` directly rather than forking
those.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.engine import Connection

from ...db import get_connection
from . import service

SESSION_COOKIE = "postwarden_session"
CSRF_HEADER = "X-CSRF-Token"


def get_current_session(request: Request, conn: Connection = Depends(get_connection)) -> dict:
    """A per-route dependency, not blanket middleware — see
    `docs/ARCHITECTURE.md`'s "Auth" section for why. Raises 401 as a
    JSON body, not a redirect: there is no login *page* for a JSON API
    route to redirect to."""
    session = service.get_session(conn, request.cookies.get(SESSION_COOKIE))
    if not session:
        raise HTTPException(401, detail="Not authenticated")
    return session


def require_csrf_header(request: Request,
                         session: dict = Depends(get_current_session)) -> dict:
    """A route that needs both "is there a valid session" and "does this
    request carry that session's own CSRF token" depends on this instead
    of `get_current_session` directly. The token travels as the
    `X-CSRF-Token` request header, out-of-body, since every field in a
    JSON request body is real payload and the CSRF token never was."""
    try:
        service.require_csrf(session, request.headers.get(CSRF_HEADER))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return session
