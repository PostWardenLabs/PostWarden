"""Central DB-exception -> user-facing message extraction.

Every write route calls this in its `except (ValueError, psycopg.Error)`
handler to surface a trigger's own `RAISE EXCEPTION` message (e.g.
"Journal lines are immutable. Post a reversing entry instead") instead
of psycopg's own noisy exception repr. Not module-specific — `entries`,
`staging`, `budget`, `imports`, `reference`, and `scheduling` all hit
this need, so it's centralized here rather than copy-pasted into each.

The backend reads through SQLAlchemy Core, not raw psycopg directly, so
a trigger's exception arrives wrapped in `sqlalchemy.exc.DBAPIError` (or
one of its subclasses — `IntegrityError`, `InternalError`, ...) with the
original `psycopg.Error` on its `.orig` attribute. `pg_message` unwraps
that first; a bare `psycopg.Error` (or anything else) is used as-is, so
this works whether the caller is going through `db.get_connection()`'s
SQLAlchemy `Connection` (the normal case) or, in a unit test, handed a
raw driver-shaped exception directly.
"""
from sqlalchemy.exc import DBAPIError


def pg_message(exc: Exception) -> str:
    """Surface the `RAISE EXCEPTION` message from a Postgres trigger,
    without the noise around it. A two-step fallback — a trigger's own
    message, or the exception's first line — unwrapping one extra layer
    first when SQLAlchemy is the one that caught it."""
    orig = exc.orig if isinstance(exc, DBAPIError) else exc
    diag = getattr(orig, "diag", None)
    if diag is not None and diag.message_primary:
        return diag.message_primary
    return str(orig).splitlines()[0]
