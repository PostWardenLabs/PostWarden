"""Schema migrations for PostWarden — plain numbered SQL files, no framework.

db/schema.sql is always the current full state, applied once by Postgres
itself on a truly fresh volume (see docker-compose.yml's
docker-entrypoint-initdb.d mount) — this module never touches a fresh
install; schema_version is already seeded to the latest migration number
by the time this runs. It only matters for an *existing* database catching
up after a `git pull`: run_migrations() applies whatever db/migrations/
files are numbered higher than schema_version and haven't run yet, in
order, each in its own transaction. Forward-only, deliberately, matching
the ledger's own append-only philosophy — a bad migration gets fixed by a
new migration, never by editing or rolling back a committed one.

Called once from app/main.py's lifespan, before the app accepts traffic.
A migration that fails raises and the app fails to boot — serving traffic
against a half-migrated schema is worse than not starting at all.
"""
from pathlib import Path

from .db import tx

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"


def pending_migrations(current: int) -> list[Path]:
    """Migration files numbered higher than `current`, in order. Exposed
    separately from run_migrations() so tests can assert on *what* would
    run without a live database."""
    files = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        try:
            n = int(f.name.split("_", 1)[0])
        except ValueError:
            continue  # not one of ours — leave room for a README, etc.
        if n > current:
            files.append((n, f))
    files.sort(key=lambda pair: pair[0])
    return [f for _, f in files]


def run_migrations() -> None:
    with tx() as cur:
        cur.execute("SELECT version FROM schema_version")
        current = cur.fetchone()["version"]

    for f in pending_migrations(current):
        n = int(f.name.split("_", 1)[0])
        with tx() as cur:
            cur.execute(f.read_text())
            cur.execute("UPDATE schema_version SET version = %s", (n,))
        current = n
