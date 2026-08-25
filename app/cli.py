"""Command-line user management for PostWarden.

Needs DATABASE_URL pointed at a running instance (same convention as the
app itself — see app/db.py). Prefer scripts/create_user.sh over calling
this directly.

Usage:
    python -m app.cli create-user <username>
    python -m app.cli reset-password <username>
"""
import getpass
import sys

from .auth import delete_all_sessions_for_user, hash_password
from .db import q1, tx

MIN_PASSWORD_LEN = 8


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
    if q1("SELECT id FROM users WHERE username = %s", (username,)):
        sys.exit(f"User {username!r} already exists — use reset-password instead.")
    password = _prompt_password()
    with tx() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, hash_password(password)))
    print(f"Created user {username!r}.")


def reset_password(username: str) -> None:
    username = username.strip().lower()
    row = q1("SELECT id FROM users WHERE username = %s", (username,))
    if not row:
        sys.exit(f"No such user: {username!r}")
    password = _prompt_password()
    with tx() as cur:
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                     (hash_password(password), row["id"]))
    delete_all_sessions_for_user(row["id"])
    print(f"Password reset for {username!r}. All existing sessions revoked.")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("create-user", "reset-password"):
        sys.exit(__doc__)
    command, username = sys.argv[1], sys.argv[2]
    (create_user if command == "create-user" else reset_password)(username)


if __name__ == "__main__":
    main()
