"""Command-line user management — the one piece of legacy `app/cli.py`
this rebuild had not ported yet (surfaced at cutover: nothing else covers
"create a login when none exists" or "I forgot my password" outside the
one-time `POSTWARDEN_ADMIN_USER`/`_PASSWORD` env-var bootstrap on first
boot, and `POST /settings/password` only works if you can already log
in). A single-user self-hosted ledger with zero account-recovery path is
a real regression, not a nice-to-have, so this ships with cutover itself
rather than as a fast-follow.

Same two subcommands, same interactive-password-prompt behavior, same
`scripts/create_user.sh` wrapper convention as legacy — deliberately not
reinvented. What differs is only what the rebuild itself already
changed: a SQLAlchemy Core `Connection`/`get_engine()` (`db.py`) instead
of legacy's psycopg-cursor `tx()`/`q1()`, and reusing `modules.auth.
service`'s own `hash_password`/`MIN_PASSWORD_LEN` and `modules.auth.
repository`'s own `user_by_username`/`insert_user`/`delete_sessions_
for_user` rather than hand-rolling SQL a second time — those already
carry the real behavior (bcrypt cost factor, username normalization
rules) and this module doesn't want a second copy to drift from them.

Needs DATABASE_URL pointed at a running instance (same convention as the
app itself — see db.py/config.py). Prefer scripts/create_user.sh over
calling this directly.

Usage:
    python -m postwarden.cli create-user <username>
    python -m postwarden.cli reset-password <username>
"""
import getpass
import sys

from .db import get_engine
from .modules.auth import repository as repo
from .modules.auth.service import MIN_PASSWORD_LEN, hash_password


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        sys.exit("Passwords don't match.")
    if len(password) < MIN_PASSWORD_LEN:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    return password


def create_user(username: str) -> None:
    username = username.strip().lower()
    with get_engine().connect() as conn, conn.begin():
        if repo.user_by_username(conn, username):
            sys.exit(f"User {username!r} already exists — use reset-password instead.")
        password = _prompt_password()
        repo.insert_user(conn, username, hash_password(password))
    print(f"Created user {username!r}.")


def reset_password(username: str) -> None:
    username = username.strip().lower()
    with get_engine().connect() as conn, conn.begin():
        user = repo.user_by_username(conn, username)
        if not user:
            sys.exit(f"No such user: {username!r}")
        password = _prompt_password()
        repo.update_password_hash(conn, user["id"], hash_password(password))
        repo.delete_sessions_for_user(conn, user["id"])
    print(f"Password reset for {username!r}. All existing sessions revoked.")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("create-user", "reset-password"):
        sys.exit(__doc__)
    command, username = sys.argv[1], sys.argv[2]
    (create_user if command == "create-user" else reset_password)(username)


if __name__ == "__main__":
    main()
