"""Database engine/connection setup — SQLAlchemy Core, not the ORM.

`db/schema.sql` is the source of truth: Core gives typed, composable
query-building for the CRUD modules, but an ORM's identity map and
unit-of-work would fight a schema whose real invariants (double-entry
balance, immutability, hierarchy integrity) live in Postgres triggers,
not in application objects. Reports go further still and call the
existing set-returning functions (`fn_trial_balance`, `fn_cash_flow_lines`,
...) as raw SQL through the same connection rather than modeling them
through Core — there's nothing to gain. This module only hands out the
connection; it has no opinion on what runs through it.

`config.Settings.database_url` already carries the SQLAlchemy-flavored
"postgresql+psycopg://" scheme (see config.py) — this module passes it to
`create_engine` unmodified.
"""
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import Connection

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    """The process-wide Engine — lazily built and cached on first use.

    Lazy on purpose: building it on first call, rather than at import
    time, means DATABASE_URL only has to be set before that first call —
    e.g. inside a test fixture — rather than before the module is even
    imported. `pool_pre_ping` guards against the connection going stale
    between requests (a reaped idle connection, a Postgres restart)
    rather than surfacing as an opaque `OperationalError` mid-request.
    """
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_connection() -> Iterator[Connection]:
    """FastAPI dependency: one Connection per request, one transaction.

    Commits on a clean return, rolls back on any raised exception, relying
    on Postgres's *deferred* constraint triggers: they fire at COMMIT, not
    at the individual INSERT, so an unbalanced journal entry raises here
    and takes the whole entry (header + lines) down with it atomically
    (see db/schema.sql and SPEC.md decision 2). Read-only routes pay for
    an always-open transaction too, rather than branching read vs. write
    paths — the cost is negligible and it keeps this dependency uniform.
    """
    with get_engine().connect() as conn:
        with conn.begin():
            yield conn
