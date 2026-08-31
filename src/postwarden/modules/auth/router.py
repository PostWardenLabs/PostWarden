"""The auth module's `APIRouter` — login/logout, the "who am I" check a
JSON SPA needs on page load, and the account-settings routes
(username/password). Mirrors every other module's shape (thin routes,
real logic in `service.py`) with two differences specific to this
module:

- **A `_bad_request` shared helper**, same reasoning `modules/reference/
  router.py`'s own copy documents: every write route here needs the
  identical `(ValueError, SQLAlchemyError) -> 400` mapping, not just
  some of them.
- **`login` doesn't use `_bad_request`** — its two failure modes
  (`service.RateLimitedError`/`InvalidCredentialsError`) get distinct
  status codes (429/401) instead of a uniform 400. See `service.py`'s
  own docstring.

Carries no router-level `dependencies=[...]` — `/login` has to stay
reachable with no session at all, and every other route here already
spells out its own `Depends(get_current_session)` or
`Depends(require_csrf_header)` per route.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ...config import Settings, get_settings
from ...db import get_connection
from ...errors import pg_message
from . import schemas, service
from .deps import SESSION_COOKIE, get_current_session, require_csrf_header

router = APIRouter(tags=["auth"])


def _bad_request(e: Exception) -> HTTPException:
    detail = pg_message(e) if isinstance(e, SQLAlchemyError) else str(e)
    return HTTPException(400, detail=detail)


@router.post("/login")
def login(payload: schemas.LoginRequest, response: Response,
          conn: Connection = Depends(get_connection),
          settings: Settings = Depends(get_settings)) -> dict:
    try:
        session = service.login(conn, payload.username, payload.password)
    except service.RateLimitedError as e:
        raise HTTPException(429, detail=str(e))
    except service.InvalidCredentialsError as e:
        raise HTTPException(401, detail=str(e))
    # The session itself is good for SESSION_TTL either way (see
    # service.create_session) — "remember me" only decides whether the
    # *cookie* survives closing the browser: no max_age at all makes it
    # a session cookie the browser drops on its own, an explicit one
    # gives it a real lifetime matching the session behind it.
    response.set_cookie(
        SESSION_COOKIE, session["token"], httponly=True, samesite="lax",
        secure=settings.postwarden_cookie_secure,
        max_age=int(service.SESSION_TTL.total_seconds()) if payload.remember else None,
    )
    return {"id": session["user_id"], "username": session["username"],
            "csrf_token": session["csrf_token"]}


@router.post("/logout")
def logout(request: Request, response: Response,
           conn: Connection = Depends(get_connection)) -> dict:
    """No CSRF check — the worst case of a bad token here is a no-op
    logout, so it's not worth gating. Idempotent: calling this with no
    session at all, or an already-expired one, still clears the cookie
    and answers success."""
    service.logout(conn, request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(session: dict = Depends(get_current_session)) -> dict:
    """The minimal "who am I, if anyone" check a JSON SPA needs on page
    load, with no server-rendered template to carry that state for free.

    Includes `csrf_token`, same as `login`'s own response, not just
    `id`/`username`: a page load riding an existing, still-valid session
    cookie (the common case — most page loads are not themselves a
    fresh `POST /login`) has no other way to learn the token its next
    write needs. Same value `login` already handed back when this
    session was created, not a new one."""
    return {"id": session["user_id"], "username": session["username"],
            "csrf_token": session["csrf_token"]}


@router.post("/settings/username")
def change_username(payload: schemas.ChangeUsernameRequest,
                     session: dict = Depends(require_csrf_header),
                     conn: Connection = Depends(get_connection)) -> dict:
    try:
        username = service.change_username(conn, session["user_id"], payload.username)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    return {"username": username}


@router.post("/settings/password")
def change_password(payload: schemas.ChangePasswordRequest, response: Response,
                     session: dict = Depends(require_csrf_header),
                     conn: Connection = Depends(get_connection)) -> dict:
    try:
        service.change_password(conn, session["user_id"], payload.current_password,
                                 payload.new_password, payload.confirm_password)
    except (ValueError, SQLAlchemyError) as e:
        raise _bad_request(e)
    # Same as the CLI's own reset-password: revoke every session for
    # this user (service.change_password already did that), then clear
    # this request's own cookie too — logging back in with the new
    # password is itself the confirmation it was set correctly.
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}
