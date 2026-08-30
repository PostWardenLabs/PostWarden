"""Central DB-exception -> user-facing message extraction.

Ported from `app/main.py`'s own `_pg_msg`, which every write route there
calls in its `except (ValueError, psycopg.Error)` handler to surface a
trigger's own `RAISE EXCEPTION` message (e.g. "Journal lines are
immutable. Post a reversing entry instead") instead of psycopg's own
noisy exception repr.

Not entries-specific, even though `modules/entries/` (Phase 1.5) is the
first module to need it — `modules/reports/` never did (read-only,
nothing it does can fail a write-side constraint), but every future
write module will (`staging`, `budget`, `imports`, `reference`,
`scheduling`) hit the exact same need, the same "documented gap, not
theoretical" reasoning `json.py` (Phase 1.3) applied to Decimal/date
encoding. Centralized here from the start rather than left to be
copy-pasted into each one later.

One real adaptation from legacy: the new backend reads through
SQLAlchemy Core, not raw psycopg directly, so a trigger's exception
arrives wrapped in `sqlalchemy.exc.DBAPIError` (or one of its
subclasses — `IntegrityError`, `InternalError`, ...) with the original
`psycopg.Error` on its `.orig` attribute. `pg_message` unwraps that
first; a bare `psycopg.Error` (or anything else) is used as-is, so this
works whether the caller is going through `db.get_connection()`'s
SQLAlchemy `Connection` (the normal case) or, in a unit test, handed a
raw driver-shaped exception directly.
"""
from sqlalchemy.exc import DBAPIError


def pg_message(exc: Exception) -> str:
    """Surface the `RAISE EXCEPTION` message from a Postgres trigger,
    without the noise around it. Mirrors legacy `_pg_msg`'s own two-step
    fallback (a trigger's own message, or the exception's first line),
    just unwrapping one extra layer first when SQLAlchemy is the one
    that caught it."""
    orig = exc.orig if isinstance(exc, DBAPIError) else exc
    diag = getattr(orig, "diag", None)
    if diag is not None and diag.message_primary:
        return diag.message_primary
    return str(orig).splitlines()[0]
