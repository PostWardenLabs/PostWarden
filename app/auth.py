"""Authentication for Libro — session cookies backed by a sessions table.

No JWT, no signing secret to manage: a session is a random opaque token
stored in Postgres (see db/schema.sql), looked up on every request. Log out
is a DELETE. Passwords are hashed with bcrypt; the hash is the only thing
that ever reaches SQL.
"""
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Request

from .db import q1, tx

SESSION_COOKIE = "libro_session"
SESSION_TTL = timedelta(days=30)

# Cookies are always HttpOnly + SameSite=Lax. The Secure flag additionally
# requires HTTPS on the connection the *browser* sees, which isn't true for
# either of this project's documented deployment paths by default (an IAP
# tunnel or a plain-HTTP Docker network both present as http://localhost —
# the encryption happens at the tunnel layer, outside the cookie's view).
# Set LIBRO_COOKIE_SECURE=true if you terminate real TLS in front of uvicorn
# yourself.
COOKIE_SECURE = os.environ.get("LIBRO_COOKIE_SECURE", "").lower() in ("1", "true", "yes")

# Minimal, single-process brute-force throttle (the Dockerfile runs one
# uvicorn worker, so an in-memory dict is consistent — it would need to move
# to the database if this ever ran with multiple workers/replicas).
_failed_logins: dict[str, list[float]] = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def is_rate_limited(username: str) -> bool:
    now = time.time()
    attempts = [t for t in _failed_logins.get(username, []) if now - t < LOGIN_WINDOW_SECONDS]
    _failed_logins[username] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS


def record_failed_login(username: str) -> None:
    _failed_logins.setdefault(username, []).append(time.time())


def clear_failed_logins(username: str) -> None:
    _failed_logins.pop(username, None)


def create_session(user_id: int) -> str:
    """Insert a new session row, return the session token to set as a cookie."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + SESSION_TTL
    with tx() as cur:
        cur.execute(
            """INSERT INTO sessions (token, user_id, csrf_token, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (token, user_id, csrf, expires))
    return token


def get_session(token: str | None):
    """Look up a session by its cookie token. Returns a dict or None."""
    if not token:
        return None
    row = q1(
        """SELECT s.token, s.user_id, s.csrf_token, s.expires_at,
                  u.username, u.is_active
             FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = %s""",
        (token,))
    if not row:
        return None
    if row["expires_at"] < datetime.now(timezone.utc):
        delete_session(token)
        return None
    if not row["is_active"]:
        return None
    return row


def delete_session(token: str) -> None:
    with tx() as cur:
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))


def delete_all_sessions_for_user(user_id: int) -> None:
    with tx() as cur:
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


def current_user(request: Request):
    """The logged-in session for this request, or None. Cheap to call
    repeatedly within one request — reads request.state, set once by the
    auth middleware in main.py."""
    return getattr(request.state, "user", None)


def bootstrap_admin_from_env() -> None:
    """First-boot convenience for Docker deployments: if LIBRO_ADMIN_USER /
    LIBRO_ADMIN_PASSWORD are set and no user exists yet at all, create one.
    Silently does nothing once any user exists, so it's safe to leave the
    env vars set across redeploys — it never overwrites a password."""
    username = os.environ.get("LIBRO_ADMIN_USER", "").strip().lower()
    password = os.environ.get("LIBRO_ADMIN_PASSWORD", "")
    if not username or not password:
        return
    if q1("SELECT id FROM users LIMIT 1"):
        return
    with tx() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, hash_password(password)))
