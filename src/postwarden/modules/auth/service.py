"""Business logic for the auth module — session/password helpers, the
brute-force login throttle.

**The single-process, in-memory login throttle (`_failed_logins`) is
deliberate, not a shortcut.** A `dict` module global is only correct
because the Dockerfile runs one uvicorn worker; moving it to the
database (correct under multiple workers/replicas) would be solving a
problem this deployment doesn't have.

`RateLimitedError`/`InvalidCredentialsError` get distinct status codes
(429/401 — see `router.py`) rather than a uniform failure response,
since a JSON API has status codes to spend.
"""
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt

from . import repository as repo

SESSION_TTL = timedelta(days=30)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
_failed_logins: dict[str, list[float]] = {}

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD_LEN = 8


class InvalidCredentialsError(ValueError):
    """Wrong username/password, or a deactivated account — deliberately
    the same message and the same exception either way, so a caller
    can't use the response to tell a real username from a nonexistent
    one."""


class RateLimitedError(ValueError):
    """This username has failed to log in too many times recently."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        # bcrypt raises on a malformed hash rather than returning False —
        # can't happen for a hash this module itself wrote, but a
        # corrupted/hand-edited row shouldn't 500 a login attempt.
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


def create_session(conn, user_id: int) -> tuple[str, str]:
    """Insert a new session row, return `(token, csrf_token)` — the
    caller sets `token` as the session cookie and hands `csrf_token`
    back to the client (see `router.login`) to echo on every
    state-changing request afterward."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    repo.insert_session(conn, user_id, token, csrf_token, expires_at)
    return token, csrf_token


def login(conn, username: str, password: str) -> dict:
    """Raises `RateLimitedError`/`InvalidCredentialsError` on failure;
    on success, returns the new session's `user_id`/`username`/`token`/
    `csrf_token`."""
    username = username.strip().lower()
    if is_rate_limited(username):
        raise RateLimitedError("Too many failed attempts — wait a few minutes and try again")
    user = repo.user_by_username(conn, username)
    if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
        record_failed_login(username)
        raise InvalidCredentialsError("Invalid username or password")
    clear_failed_logins(username)
    token, csrf_token = create_session(conn, user["id"])
    return {"user_id": user["id"], "username": user["username"], "token": token,
            "csrf_token": csrf_token}


def get_session(conn, token: str | None) -> dict | None:
    """Look up a session by its cookie token: exists, not expired
    (deleting it if so — lazy cleanup on next use, since there's no cron
    in this deployment to sweep `sessions` otherwise), and the user
    behind it is still active."""
    if not token:
        return None
    session = repo.session_by_token(conn, token)
    if not session:
        return None
    if session["expires_at"] < datetime.now(timezone.utc):
        repo.delete_session(conn, token)
        return None
    if not session["is_active"]:
        return None
    return session


def logout(conn, token: str | None) -> None:
    if token:
        repo.delete_session(conn, token)


def require_csrf(session: dict | None, token: str | None) -> None:
    """Raise `ValueError` (caught the same uniform way as any other bad
    input, per every other write module's own convention) if `token`
    doesn't match this session's own `csrf_token`. Travels as the
    `X-CSRF-Token` request header — see `router.py`'s own docstring."""
    if not session or not token or not secrets.compare_digest(token, session["csrf_token"]):
        raise ValueError("Your session expired or the form was stale — please retry.")


def change_username(conn, user_id: int, username: str) -> str:
    """Returns the normalized username on success. A collision with
    someone else's name surfaces as a plain `sqlalchemy.exc.
    IntegrityError` from `repository.update_username`'s own `UPDATE` —
    left to the caller to catch alongside `ValueError`, same as every
    other write module's `(ValueError, SQLAlchemyError)` convention,
    rather than pre-checked here (pre-checking would just be a second
    query racing the same unique constraint anyway)."""
    username = username.strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise ValueError(
            "Username must be 3-32 characters: lowercase letters, numbers, _ . or - only")
    repo.update_username(conn, user_id, username)
    return username


def change_password(conn, user_id: int, current_password: str, new_password: str,
                     confirm_password: str) -> None:
    """On success, revokes every session for this user (including the
    one making this request) — logging back in with the new password is
    itself the confirmation it was set correctly. `router.py` is what
    actually clears the caller's own cookie."""
    user = repo.user_by_id(conn, user_id)
    if not user or not verify_password(current_password, user["password_hash"]):
        raise ValueError("Current password is incorrect")
    if new_password != confirm_password:
        raise ValueError("New password and confirmation don't match")
    if len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"New password must be at least {MIN_PASSWORD_LEN} characters")
    repo.update_password_hash(conn, user_id, hash_password(new_password))
    repo.delete_sessions_for_user(conn, user_id)


def bootstrap_admin_from_env(conn, username: str, password: str) -> None:
    """First-boot convenience for Docker deployments — takes the two env
    values as plain arguments rather than reading `os.environ` itself,
    so this module stays framework/env-decoupled like every other
    module's `service.py`. Reading `settings.postwarden_admin_user`/
    `_password` and calling this at startup is `main.py`'s own lifespan
    hook.

    Silently does nothing once any user exists, so it's safe to leave
    the env vars set across redeploys — it never overwrites a password."""
    username = username.strip().lower()
    if not username or not password:
        return
    if repo.any_user_exists(conn):
        return
    repo.insert_user(conn, username, hash_password(password))
