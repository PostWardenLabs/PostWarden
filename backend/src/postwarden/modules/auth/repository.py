"""SQL access for `users`/`sessions` — ported from `app/auth.py`'s own
`q`/`q1`/`tx` calls and the handful of raw queries `app/main.py`'s Auth/
User settings sections ran inline (`login_submit`'s user lookup,
`change_username`/`change_password`'s `UPDATE users`). No other module
forks any of this: `users`/`sessions` are wholly owned by this module —
nothing else in the schema references them except `journal_entries.
created_by_user_id`/`import_batches.imported_by_user_id`, which are
plain nullable FKs a future phase's own attribution write reads/sets
directly, not something this module needs to expose a lookup for.
"""
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection


def user_by_username(conn: Connection, username: str) -> dict | None:
    row = conn.execute(text(
        "SELECT id, username, password_hash, is_active FROM users WHERE username = :username"
    ), {"username": username}).mappings().first()
    return dict(row) if row else None


def user_by_id(conn: Connection, user_id: int) -> dict | None:
    row = conn.execute(text(
        "SELECT id, username, password_hash, is_active FROM users WHERE id = :id"
    ), {"id": user_id}).mappings().first()
    return dict(row) if row else None


def any_user_exists(conn: Connection) -> bool:
    return conn.execute(text("SELECT id FROM users LIMIT 1")).first() is not None


def insert_user(conn: Connection, username: str, password_hash: str) -> int:
    row = conn.execute(text(
        "INSERT INTO users (username, password_hash) VALUES (:username, :password_hash) "
        "RETURNING id"
    ), {"username": username, "password_hash": password_hash}).mappings().one()
    return row["id"]


def update_username(conn: Connection, user_id: int, username: str) -> None:
    """No rowcount check — an unknown `user_id` here would mean the
    caller's own session pointed at a user row that no longer exists,
    which `deps.get_current_session` already rules out by construction
    (its own join would have found no session first). `users.username`'s
    own `UNIQUE` constraint is what actually needs to raise here, on a
    collision with someone else's name — surfaced to the caller as a
    plain `sqlalchemy.exc.IntegrityError`, same as legacy's own
    unguarded `UPDATE` let `psycopg.errors.UniqueViolation` bubble up
    to its `except psycopg.Error` handler."""
    conn.execute(text("UPDATE users SET username = :username WHERE id = :id"),
                 {"username": username, "id": user_id})


def update_password_hash(conn: Connection, user_id: int, password_hash: str) -> None:
    conn.execute(text("UPDATE users SET password_hash = :password_hash WHERE id = :id"),
                 {"password_hash": password_hash, "id": user_id})


def insert_session(conn: Connection, user_id: int, token: str, csrf_token: str,
                    expires_at: datetime) -> None:
    conn.execute(text(
        "INSERT INTO sessions (token, user_id, csrf_token, expires_at) "
        "VALUES (:token, :user_id, :csrf_token, :expires_at)"
    ), {"token": token, "user_id": user_id, "csrf_token": csrf_token, "expires_at": expires_at})


def session_by_token(conn: Connection, token: str) -> dict | None:
    """Joins `users` the same way legacy `auth.get_session`'s own query
    does, so a caller gets `user_id`/`username`/`is_active`/`csrf_token`/
    `expires_at` in one round trip rather than two."""
    row = conn.execute(text("""
        SELECT s.token, s.user_id, s.csrf_token, s.expires_at, u.username, u.is_active
          FROM sessions s JOIN users u ON u.id = s.user_id
         WHERE s.token = :token
    """), {"token": token}).mappings().first()
    return dict(row) if row else None


def delete_session(conn: Connection, token: str) -> None:
    conn.execute(text("DELETE FROM sessions WHERE token = :token"), {"token": token})


def delete_sessions_for_user(conn: Connection, user_id: int) -> None:
    conn.execute(text("DELETE FROM sessions WHERE user_id = :user_id"), {"user_id": user_id})
